#!/usr/bin/env bash
set -eEuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="infra/compose/docker-compose.test.yml"
REPORT_DIR="docs/testing"
REPORT_FILE="$REPORT_DIR/TEST_EXECUTION_REPORT.md"
SUMMARY_FILE="$REPORT_DIR/TEST_EXECUTION_SUMMARY.json"
RUN_ID="$(date -u +"%Y%m%dT%H%M%SZ")"
RUN_DIR="$REPORT_DIR/test-runs/$RUN_ID"
RUN_REPORT_FILE="$RUN_DIR/TEST_EXECUTION_REPORT.md"
RUN_SUMMARY_FILE="$RUN_DIR/TEST_EXECUTION_SUMMARY.json"
META_FILE="$RUN_DIR/suites.tsv"
RUN_META_FILE="$RUN_DIR/run-meta.json"

SUITE_LOG_DIR="$RUN_DIR/suites"
SUITE_JUNIT_DIR="$RUN_DIR/junit"
INFRA_DIR="$RUN_DIR/infra"
INFRA_SERVICES_DIR="$INFRA_DIR/services"
INFRA_INSPECT_DIR="$INFRA_DIR/inspect"

RETAIN_LOGS="on-failure"
KEEP_VOLUMES=false
NO_CLEANUP=false
RUN_INTEGRATION_ON_READINESS_FAILURE=false
INTEGRATION_MODE="sequential"
MAX_PARALLEL=2
PARALLEL_SAFE_SERVICES=()

COMPOSE_STARTED=false
INFRA_DIAGNOSTICS_CAPTURED=false
READINESS_OK=false
TEST_FAILURES=false
TOTAL_COLLECTED=0
RUN_STARTED_EPOCH="$(date +%s)"
RUN_STARTED_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

usage() {
  cat <<'USAGE'
Usage: scripts/test-full.sh [options]

Options:
  --retain-logs <always|on-failure|none>      Log retention policy (default: on-failure)
  --keep-volumes                               Keep docker volumes on compose down
  --no-cleanup                                 Skip compose down at script exit
  --run-integration-on-readiness-failure       Run integration/e2e even when readiness fails
  --integration-mode <sequential|parallel-safe>
                                               Execution mode for integration/e2e (default: sequential)
  --max-parallel <N>                           Reserved for parallel-safe mode (default: 2)
  --parallel-safe-services <svc1,svc2,...>     Allowlist for parallel-safe mode
  -h, --help                                   Show this help message
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --retain-logs)
      RETAIN_LOGS="${2:-}"
      shift 2
      ;;
    --keep-volumes)
      KEEP_VOLUMES=true
      shift
      ;;
    --no-cleanup)
      NO_CLEANUP=true
      shift
      ;;
    --run-integration-on-readiness-failure)
      RUN_INTEGRATION_ON_READINESS_FAILURE=true
      shift
      ;;
    --integration-mode)
      INTEGRATION_MODE="${2:-}"
      shift 2
      ;;
    --max-parallel)
      MAX_PARALLEL="${2:-}"
      shift 2
      ;;
    --parallel-safe-services)
      IFS=',' read -r -a PARALLEL_SAFE_SERVICES <<< "${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ "$RETAIN_LOGS" != "always" && "$RETAIN_LOGS" != "on-failure" && "$RETAIN_LOGS" != "none" ]]; then
  echo "ERROR: --retain-logs must be one of: always, on-failure, none" >&2
  exit 2
fi

if [[ "$INTEGRATION_MODE" != "sequential" && "$INTEGRATION_MODE" != "parallel-safe" ]]; then
  echo "ERROR: --integration-mode must be one of: sequential, parallel-safe" >&2
  exit 2
fi

if ! [[ "$MAX_PARALLEL" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: --max-parallel must be a positive integer" >&2
  exit 2
fi

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" && -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
fi
if [[ -z "$PYTHON" && -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON="${VIRTUAL_ENV}/bin/python"
fi
if [[ -z "$PYTHON" ]]; then
  for _py in python3.12 python3 python; do
    if command -v "$_py" >/dev/null 2>&1; then
      PYTHON="$_py"
      break
    fi
  done
fi
if [[ -z "$PYTHON" ]]; then
  echo "ERROR: No Python interpreter found. Set PYTHON=..." >&2
  exit 1
fi

mkdir -p "$RUN_DIR" "$SUITE_LOG_DIR" "$SUITE_JUNIT_DIR" "$INFRA_SERVICES_DIR" "$INFRA_INSPECT_DIR"

printf "label\tstatus\tcollected\tlayer\tsuite_type\tduration_sec\tlog\txml\tfailure_type\treason\n" > "$META_FILE"

slugify() {
  printf "%s" "$1" | tr '/: ()' '_____'
}

has_pytest_files() {
  local dir="$1"
  [[ -d "$dir" ]] || return 1
  find "$dir" -type f \( -name "test_*.py" -o -name "*_test.py" \) -print -quit | grep -q .
}

record_suite() {
  local label="$1"
  local status="$2"
  local collected="$3"
  local layer="$4"
  local suite_type="$5"
  local duration_sec="$6"
  local log_path="$7"
  local xml_path="$8"
  local failure_type="$9"
  local reason="${10:-}"

  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
    "$label" "$status" "$collected" "$layer" "$suite_type" "$duration_sec" "$log_path" "$xml_path" "$failure_type" "$reason" >> "$META_FILE"

  if [[ "$status" == "failed" ]]; then
    TEST_FAILURES=true
  fi
}

record_skip() {
  local label="$1"
  local layer="$2"
  local suite_type="$3"
  local reason="$4"
  record_suite "$label" "skipped" "0" "$layer" "$suite_type" "0" "" "" "no_tests" "$reason"
}

collect_count() {
  local collect_log="$1"
  "$PYTHON" - "$collect_log" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
patterns = [
    r"collected\s+\d+\s+items\s*/\s*\d+\s+deselected\s*/\s*(\d+)\s+selected",
    r"(\d+)\s+selected",
    r"collected\s+(\d+)\s+items",
    r"(\d+)\s+tests\s+collected",
]
for pattern in patterns:
    match = re.search(pattern, text)
    if match:
        print(match.group(1))
        raise SystemExit(0)
print("0")
PY
}

classify_pytest_failure_type() {
  local rc="$1"
  case "$rc" in
    1) printf "assertion" ;;
    2) printf "collection" ;;
    3) printf "error" ;;
    4) printf "script_failure" ;;
    5) printf "no_tests" ;;
    *) printf "unknown" ;;
  esac
}

run_pytest_suite() {
  local label="$1"
  local layer="$2"
  local suite_type="$3"
  local python_cmd="$4"
  shift 4

  local slug
  slug="$(slugify "$label")"
  local collect_log="$SUITE_LOG_DIR/${slug}.collect.log"
  local run_log="$SUITE_LOG_DIR/${slug}.log"
  local xml_path="$SUITE_JUNIT_DIR/${slug}.xml"
  local collected
  local rc
  local start_epoch
  local end_epoch
  local duration
  local failure_type

  set +e
  "$python_cmd" -m pytest "$@" --collect-only > "$collect_log" 2>&1
  set -e

  collected="$(collect_count "$collect_log")"
  TOTAL_COLLECTED=$((TOTAL_COLLECTED + collected))

  start_epoch="$(date +%s)"
  set +e
  "$python_cmd" -m pytest "$@" -v --tb=long --maxfail=0 --junitxml "$xml_path" > "$run_log" 2>&1
  rc=$?
  set -e
  end_epoch="$(date +%s)"
  duration=$((end_epoch - start_epoch))
  failure_type="$(classify_pytest_failure_type "$rc")"

  if [[ $rc -eq 0 ]]; then
    record_suite "$label" "passed" "$collected" "$layer" "$suite_type" "$duration" "$run_log" "$xml_path" "" ""
  elif [[ $rc -eq 5 ]]; then
    record_suite "$label" "skipped" "$collected" "$layer" "$suite_type" "$duration" "$run_log" "$xml_path" "no_tests" "no tests collected"
  else
    record_suite "$label" "failed" "$collected" "$layer" "$suite_type" "$duration" "$run_log" "$xml_path" "$failure_type" "pytest exited with code $rc"
  fi
}

run_repo_pytest_suite() {
  local label="$1"
  local layer="$2"
  local suite_type="$3"
  shift 3
  run_pytest_suite "$label" "$layer" "$suite_type" "$PYTHON" "$@"
}

run_service_suite() {
  local service="$1"
  local label="$2"
  local layer="$3"
  local suite_type="$4"
  local rel_tests_path="$5"
  shift 5

  local service_dir="$ROOT_DIR/services/$service"
  local service_python="$PYTHON"
  if [[ -x "$service_dir/.venv/bin/python" ]]; then
    service_python="$service_dir/.venv/bin/python"
    if ! "$service_python" -m pip --version >/dev/null 2>&1; then
      "$service_python" -m ensurepip --upgrade >/dev/null 2>&1 || true
    fi
    # Refresh service venv dependencies with local shared libs first.
    # This avoids stale environments missing transitive deps (e.g., uuid6 via libs/common).
    set +e
    for lib_dir in "$ROOT_DIR"/libs/*; do
      [[ -d "$lib_dir" && -f "$lib_dir/pyproject.toml" ]] || continue
      "$service_python" -m pip install -q -e "$lib_dir" >/dev/null 2>&1 || true
    done
    if [[ -f "$service_dir/pyproject.toml" ]]; then
      (cd "$service_dir" && "$service_python" -m pip install -q -e ".[dev]" >/dev/null 2>&1 \
        || "$service_python" -m pip install -q -e "." >/dev/null 2>&1) || true
    fi
    set -e
  fi

  # For services using src/ layout without a dedicated venv, expose the package
  # source to Python so imports work without a prior editable install.
  local svc_pythonpath="${PYTHONPATH:-}"
  if [[ -d "$service_dir/src" ]]; then
    svc_pythonpath="$service_dir/src${svc_pythonpath:+:$svc_pythonpath}"
  fi

  local slug
  slug="$(slugify "$label")"
  local collect_log="$SUITE_LOG_DIR/${slug}.collect.log"
  local run_log="$SUITE_LOG_DIR/${slug}.log"
  local xml_path="$SUITE_JUNIT_DIR/${slug}.xml"
  local collected
  local rc
  local start_epoch
  local end_epoch
  local duration
  local failure_type

  set +e
  (
    cd "$service_dir"
    [[ -n "$svc_pythonpath" ]] && export PYTHONPATH="$svc_pythonpath"
    "$service_python" -m pytest "$rel_tests_path" "$@" --collect-only
  ) > "$collect_log" 2>&1
  set -e

  collected="$(collect_count "$collect_log")"
  TOTAL_COLLECTED=$((TOTAL_COLLECTED + collected))

  start_epoch="$(date +%s)"
  set +e
  (
    cd "$service_dir"
    [[ -n "$svc_pythonpath" ]] && export PYTHONPATH="$svc_pythonpath"
    "$service_python" -m pytest "$rel_tests_path" "$@" -v --tb=long --maxfail=0 --junitxml "$ROOT_DIR/$xml_path"
  ) > "$run_log" 2>&1
  rc=$?
  set -e
  end_epoch="$(date +%s)"
  duration=$((end_epoch - start_epoch))
  failure_type="$(classify_pytest_failure_type "$rc")"

  if [[ $rc -eq 0 ]]; then
    record_suite "$label" "passed" "$collected" "$layer" "$suite_type" "$duration" "$run_log" "$xml_path" "" ""
  elif [[ $rc -eq 5 ]]; then
    record_suite "$label" "skipped" "$collected" "$layer" "$suite_type" "$duration" "$run_log" "$xml_path" "no_tests" "no tests collected"
  else
    record_suite "$label" "failed" "$collected" "$layer" "$suite_type" "$duration" "$run_log" "$xml_path" "$failure_type" "pytest exited with code $rc"
  fi
}

capture_infra_diagnostics() {
  if [[ "$INFRA_DIAGNOSTICS_CAPTURED" == "true" ]]; then
    return 0
  fi
  if [[ "$COMPOSE_STARTED" != "true" ]]; then
    return 0
  fi

  INFRA_DIAGNOSTICS_CAPTURED=true

  docker compose -f "$COMPOSE_FILE" --profile all ps > "$INFRA_DIR/compose.ps.txt" 2>&1 || true
  docker compose -f "$COMPOSE_FILE" --profile all config > "$INFRA_DIR/compose.config.yaml" 2>&1 || true
  docker compose -f "$COMPOSE_FILE" --profile all logs --no-color --timestamps > "$INFRA_DIR/compose.all.log" 2>&1 || true

  local services
  services="$(docker compose -f "$COMPOSE_FILE" --profile all ps --services 2>/dev/null || true)"
  if [[ -n "$services" ]]; then
    while IFS= read -r svc; do
      [[ -n "$svc" ]] || continue
      docker compose -f "$COMPOSE_FILE" --profile all logs --no-color --timestamps "$svc" > "$INFRA_SERVICES_DIR/${svc}.log" 2>&1 || true
    done <<< "$services"
  fi

  local container_ids
  container_ids="$(docker compose -f "$COMPOSE_FILE" --profile all ps -q 2>/dev/null || true)"
  if [[ -n "$container_ids" ]]; then
    while IFS= read -r cid; do
      [[ -n "$cid" ]] || continue
      docker inspect "$cid" > "$INFRA_INSPECT_DIR/${cid}.json" 2>&1 || true
    done <<< "$container_ids"
  fi
}

teardown_compose() {
  if [[ "$COMPOSE_STARTED" != "true" ]]; then
    return 0
  fi
  if [[ "$NO_CLEANUP" == "true" ]]; then
    return 0
  fi

  local down_args=(docker compose -f "$COMPOSE_FILE" --profile all down)
  if [[ "$KEEP_VOLUMES" == "false" ]]; then
    down_args+=( -v )
  fi
  "${down_args[@]}" >/dev/null 2>&1 || true
  COMPOSE_STARTED=false
}

finalize_infra_artifacts() {
  case "$RETAIN_LOGS" in
    always)
      capture_infra_diagnostics
      ;;
    on-failure)
      if [[ "$TEST_FAILURES" == "true" ]]; then
        capture_infra_diagnostics
      fi
      ;;
    none)
      ;;
  esac
}

cleanup() {
  finalize_infra_artifacts
  teardown_compose
}
trap cleanup EXIT

GIT_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
GIT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
PYTHON_VERSION_STR="$("$PYTHON" --version 2>&1 || true)"
DOCKER_VERSION_STR="$(docker --version 2>/dev/null || echo 'docker unavailable')"
DOCKER_COMPOSE_VERSION_STR="$(docker compose version 2>/dev/null || echo 'docker compose unavailable')"
HOSTNAME_STR="$(hostname 2>/dev/null || echo unknown)"

cat > "$RUN_META_FILE" <<EOF
{
  "run_id": "$RUN_ID",
  "run_started_at_utc": "$RUN_STARTED_UTC",
  "repo_root": "$ROOT_DIR",
  "git_sha": "$GIT_SHA",
  "git_branch": "$GIT_BRANCH",
  "python": "$PYTHON",
  "python_version": "$PYTHON_VERSION_STR",
  "docker_version": "$DOCKER_VERSION_STR",
  "docker_compose_version": "$DOCKER_COMPOSE_VERSION_STR",
  "hostname": "$HOSTNAME_STR",
  "retain_logs": "$RETAIN_LOGS",
  "keep_volumes": "$KEEP_VOLUMES",
  "no_cleanup": "$NO_CLEANUP",
  "integration_mode": "$INTEGRATION_MODE",
  "max_parallel": "$MAX_PARALLEL",
  "run_integration_on_readiness_failure": "$RUN_INTEGRATION_ON_READINESS_FAILURE"
}
EOF

echo "Starting full layered test suite..."

echo "Layer 1: architecture tests"
run_repo_pytest_suite "architecture" "architecture" "pytest" tests/architecture

echo "Layer 2: library tests"
libs_log="$SUITE_LOG_DIR/libs.log"
libs_start="$(date +%s)"
set +e
PYTHON="$PYTHON" ./scripts/test-libs.sh > "$libs_log" 2>&1
libs_rc=$?
set -e
libs_end="$(date +%s)"
libs_duration=$((libs_end - libs_start))
if [[ $libs_rc -eq 0 ]]; then
  record_suite "libs" "passed" "0" "libs" "script" "$libs_duration" "$libs_log" "" "" "summarized by scripts/test-libs.sh"
else
  record_suite "libs" "failed" "0" "libs" "script" "$libs_duration" "$libs_log" "" "script_failure" "scripts/test-libs.sh exited with code $libs_rc"
fi

echo "Layer 3: service unit tests"
for svc_dir in services/*; do
  [[ -d "$svc_dir" ]] || continue
  service="$(basename "$svc_dir")"
  tests_dir="$svc_dir/tests"

  if [[ ! -d "$tests_dir" ]]; then
    record_skip "${service}:unit" "unit" "pytest" "no tests dir"
    continue
  fi

  echo "- services/$service"
  if has_pytest_files "$tests_dir/unit"; then
    run_service_suite "$service" "${service}:unit" "unit" "pytest" "tests/unit" -m "not live and not slow"
  elif has_pytest_files "$tests_dir"; then
    run_service_suite \
      "$service" \
      "${service}:unit" \
      "unit" \
      "pytest" \
      "tests" \
      -m "not integration and not e2e and not live and not slow and not contract" \
      --ignore "tests/integration" \
      --ignore "tests/e2e" \
      --ignore "tests/live" \
      --ignore "tests/contract" \
      --ignore "tests/platform_qa"
  else
    record_skip "${service}:unit" "unit" "pytest" "no unit tests"
  fi
done

echo "Layer 4: service contract tests"
for svc_dir in services/*; do
  [[ -d "$svc_dir" ]] || continue
  service="$(basename "$svc_dir")"
  contract_dir="$svc_dir/tests/contract"

  if [[ ! -d "$contract_dir" ]]; then
    record_skip "${service}:contract" "contract" "pytest" "no contract dir"
    continue
  fi

  if ! has_pytest_files "$contract_dir"; then
    record_skip "${service}:contract" "contract" "pytest" "no contract tests"
    continue
  fi

  run_service_suite "$service" "${service}:contract" "contract" "pytest" "tests/contract" -m contract
done

echo "Layer 5: compose-backed integration and e2e"
infra_start_start="$(date +%s)"
set +e
docker compose -f "$COMPOSE_FILE" --profile all up --build --wait > "$INFRA_DIR/compose.up.log" 2>&1
compose_up_rc=$?
set -e
infra_start_end="$(date +%s)"
infra_start_duration=$((infra_start_end - infra_start_start))

if [[ $compose_up_rc -eq 0 ]]; then
  COMPOSE_STARTED=true
  record_suite "compose:up" "passed" "0" "infra" "compose_startup" "$infra_start_duration" "$INFRA_DIR/compose.up.log" "" "" ""
else
  TEST_FAILURES=true
  record_suite "compose:up" "failed" "0" "infra" "compose_startup" "$infra_start_duration" "$INFRA_DIR/compose.up.log" "" "infra_startup" "docker compose up failed (exit $compose_up_rc)"
fi

if [[ "$COMPOSE_STARTED" == "true" ]]; then
  readiness_start="$(date +%s)"
  set +e
  ./scripts/wait-for-services.sh all > "$INFRA_DIR/compose.readiness.log" 2>&1
  readiness_rc=$?
  set -e
  readiness_end="$(date +%s)"
  readiness_duration=$((readiness_end - readiness_start))

  if [[ $readiness_rc -eq 0 ]]; then
    READINESS_OK=true
    record_suite "compose:readiness" "passed" "0" "infra" "readiness" "$readiness_duration" "$INFRA_DIR/compose.readiness.log" "" "" ""
  else
    TEST_FAILURES=true
    record_suite "compose:readiness" "failed" "0" "infra" "readiness" "$readiness_duration" "$INFRA_DIR/compose.readiness.log" "" "infra_readiness" "services not ready"
  fi
fi

should_run_integration=false
if [[ "$COMPOSE_STARTED" == "true" && "$READINESS_OK" == "true" ]]; then
  should_run_integration=true
elif [[ "$COMPOSE_STARTED" == "true" && "$READINESS_OK" != "true" && "$RUN_INTEGRATION_ON_READINESS_FAILURE" == "true" ]]; then
  should_run_integration=true
fi

if [[ "$should_run_integration" == "true" ]]; then
  if [[ "$INTEGRATION_MODE" == "parallel-safe" && ${#PARALLEL_SAFE_SERVICES[@]} -eq 0 ]]; then
    echo "parallel-safe mode requested but no services were allowlisted; running sequentially."
  fi

  for svc_dir in services/*; do
    [[ -d "$svc_dir" ]] || continue
    service="$(basename "$svc_dir")"

    integration_dir="$svc_dir/tests/integration"
    if has_pytest_files "$integration_dir"; then
      run_service_suite "$service" "${service}:integration" "integration" "pytest" "tests/integration" -m integration
    else
      record_skip "${service}:integration" "integration" "pytest" "no integration tests"
    fi

    e2e_dir="$svc_dir/tests/e2e"
    if has_pytest_files "$e2e_dir"; then
      run_service_suite "$service" "${service}:e2e" "e2e" "pytest" "tests/e2e" -m e2e
    else
      record_skip "${service}:e2e" "e2e" "pytest" "no e2e tests"
    fi
  done
else
  for svc_dir in services/*; do
    [[ -d "$svc_dir" ]] || continue
    service="$(basename "$svc_dir")"
    if has_pytest_files "$svc_dir/tests/integration"; then
      record_suite "${service}:integration" "skipped" "0" "integration" "pytest" "0" "" "" "setup" "integration skipped due to infra startup/readiness failure"
    else
      record_skip "${service}:integration" "integration" "pytest" "no integration tests"
    fi
    if has_pytest_files "$svc_dir/tests/e2e"; then
      record_suite "${service}:e2e" "skipped" "0" "e2e" "pytest" "0" "" "" "setup" "e2e skipped due to infra startup/readiness failure"
    else
      record_skip "${service}:e2e" "e2e" "pytest" "no e2e tests"
    fi
  done
fi

RUN_ENDED_EPOCH="$(date +%s)"
RUN_DURATION=$((RUN_ENDED_EPOCH - RUN_STARTED_EPOCH))
RUN_ENDED_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

"$PYTHON" - "$META_FILE" "$RUN_REPORT_FILE" "$RUN_SUMMARY_FILE" "$RUN_DIR" "$TOTAL_COLLECTED" "$RUN_META_FILE" "$RUN_STARTED_UTC" "$RUN_ENDED_UTC" "$RUN_DURATION" <<'PY'
from __future__ import annotations

import csv
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

meta_path = Path(sys.argv[1])
report_path = Path(sys.argv[2])
summary_path = Path(sys.argv[3])
run_dir = Path(sys.argv[4])
total_collected = int(sys.argv[5])
run_meta_path = Path(sys.argv[6])
run_started_utc = sys.argv[7]
run_ended_utc = sys.argv[8]
run_duration = int(sys.argv[9])

rows: list[dict[str, str]] = []
with meta_path.open("r", encoding="utf-8", newline="") as f:
    rows.extend(csv.DictReader(f, delimiter="\t"))

run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))

passed = [r for r in rows if r["status"] == "passed"]
failed = [r for r in rows if r["status"] == "failed"]
skipped = [r for r in rows if r["status"] == "skipped"]
infra_rows = [r for r in rows if r.get("layer") == "infra"]

failed_tests: list[dict[str, str]] = []
for row in failed:
    xml_path = row.get("xml", "").strip()
    if not xml_path:
        continue
    xml_file = Path(xml_path)
    if not xml_file.exists():
        failed_tests.append(
            {
                "suite": row["label"],
                "name": "<suite-level failure>",
                "kind": row.get("failure_type") or "suite",
                "reason": row.get("reason") or "no xml found",
                "trace": "",
                "log": row.get("log", ""),
            }
        )
        continue

    root = ET.parse(xml_file).getroot()
    for case in root.iter("testcase"):
        failure = case.find("failure")
        error = case.find("error")
        if failure is None and error is None:
            continue
        node = failure if failure is not None else error
        classname = case.attrib.get("classname", "")
        name = case.attrib.get("name", "")
        test_name = f"{classname}::{name}" if classname else name
        reason = node.attrib.get("message", "") if node is not None else ""
        trace_text = (node.text or "") if node is not None else ""
        trace_lines = [line.rstrip() for line in trace_text.splitlines() if line.strip()]
        trace_excerpt = "\n".join(trace_lines[:25])
        failed_tests.append(
            {
                "suite": row["label"],
                "name": test_name,
                "kind": "failure" if failure is not None else "error",
                "reason": reason.strip() or "no explicit reason",
                "trace": trace_excerpt,
                "log": row.get("log", ""),
            }
        )


        def _to_int(value: str) -> int:
          try:
            return int(value)
          except (TypeError, ValueError):
            return 0


        def _service_from_label(label: str) -> str:
          if ":" in label:
            return label.split(":", 1)[0]
          if label.startswith("compose:"):
            return "infra"
          return label


        failed_tests_by_suite = Counter(item["suite"] for item in failed_tests)

        by_layer: dict[str, dict[str, int]] = defaultdict(
          lambda: {
            "suites_total": 0,
            "suites_passed": 0,
            "suites_failed": 0,
            "suites_skipped": 0,
            "collected_tests": 0,
            "duration_sec": 0,
            "failed_tests": 0,
          }
        )

        by_service: dict[str, dict[str, int]] = defaultdict(
          lambda: {
            "suites_total": 0,
            "suites_passed": 0,
            "suites_failed": 0,
            "suites_skipped": 0,
            "collected_tests": 0,
            "duration_sec": 0,
            "failed_tests": 0,
          }
        )

        for row in rows:
          label = row["label"]
          layer = row["layer"]
          service = _service_from_label(label)
          status = row["status"]
          collected = _to_int(row.get("collected", "0"))
          duration = _to_int(row.get("duration_sec", "0"))
          failed_in_suite = failed_tests_by_suite.get(label, 0)

          for bucket in (by_layer[layer], by_service[service]):
            bucket["suites_total"] += 1
            bucket[f"suites_{status}"] += 1
            bucket["collected_tests"] += collected
            bucket["duration_sec"] += duration
            bucket["failed_tests"] += failed_in_suite

        execution_metrics = {
          "collected_tests": total_collected,
          "collected_in_passed_or_failed_suites": sum(
            _to_int(r.get("collected", "0")) for r in rows if r.get("status") in {"passed", "failed"}
          ),
          "collected_in_skipped_suites": sum(_to_int(r.get("collected", "0")) for r in rows if r.get("status") == "skipped"),
          "failed_tests": len(failed_tests),
        }

        by_layer_list = [
          {
            "layer": layer,
            **metrics,
          }
          for layer, metrics in sorted(by_layer.items(), key=lambda kv: kv[0])
        ]

        by_service_list = [
          {
            "service": service,
            **metrics,
          }
          for service, metrics in sorted(by_service.items(), key=lambda kv: kv[0])
        ]

summary = {
    "run": {
        "run_id": run_meta.get("run_id"),
        "started_at_utc": run_started_utc,
        "ended_at_utc": run_ended_utc,
        "duration_sec": run_duration,
        "artifacts_dir": run_dir.as_posix(),
        "metadata": run_meta,
    },
    "counts": {
        "suites_passed": len(passed),
        "suites_failed": len(failed),
        "suites_skipped": len(skipped),
        "total_collected_tests": total_collected,
        "failed_tests": len(failed_tests),
    },
    "aggregates": {
      "execution": execution_metrics,
      "by_layer": by_layer_list,
      "by_service": by_service_list,
      "failed_tests_by_suite": dict(sorted(failed_tests_by_suite.items(), key=lambda kv: (-kv[1], kv[0]))),
    },
    "infra": {
        "status": "failed" if any(r["status"] == "failed" for r in infra_rows) else "passed",
        "artifacts": {
            "compose_ps": f"{run_dir.as_posix()}/infra/compose.ps.txt",
            "compose_config": f"{run_dir.as_posix()}/infra/compose.config.yaml",
            "compose_all_log": f"{run_dir.as_posix()}/infra/compose.all.log",
            "services_logs_dir": f"{run_dir.as_posix()}/infra/services",
            "inspect_dir": f"{run_dir.as_posix()}/infra/inspect",
        },
    },
    "suites": rows,
    "failed_tests": failed_tests,
}

summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

lines: list[str] = []
lines.append("# Test Execution Report")
lines.append("")
lines.append(f"Generated at: {run_ended_utc}")
lines.append(f"Run ID: {run_meta.get('run_id', 'unknown')}")
lines.append(f"Run artifacts: {run_dir.as_posix()}")
lines.append(f"Run duration (sec): {run_duration}")
lines.append("")
lines.append("## Environment")
lines.append(f"- git branch: {run_meta.get('git_branch', 'unknown')}")
lines.append(f"- git sha: {run_meta.get('git_sha', 'unknown')}")
lines.append(f"- python: {run_meta.get('python_version', 'unknown')}")
lines.append(f"- docker: {run_meta.get('docker_version', 'unknown')}")
lines.append(f"- docker compose: {run_meta.get('docker_compose_version', 'unknown')}")
lines.append(f"- retain logs: {run_meta.get('retain_logs', 'unknown')}")
lines.append(f"- integration mode: {run_meta.get('integration_mode', 'unknown')}")
lines.append("")
lines.append("## Summary")
lines.append(f"- Test suites passed: {len(passed)}")
lines.append(f"- Test suites failed: {len(failed)}")
lines.append(f"- Test suites skipped: {len(skipped)}")
lines.append(f"- Total collected tests: {total_collected}")
lines.append(f"- Total failed tests: {len(failed_tests)}")
lines.append("- Note: suite counts and test counts are different units")
lines.append("")
lines.append("## Aggregated Metrics")
lines.append(f"- Collected in passed/failed suites: {execution_metrics['collected_in_passed_or_failed_suites']}")
lines.append(f"- Collected in skipped suites: {execution_metrics['collected_in_skipped_suites']}")
lines.append(f"- Failed tests extracted from JUnit: {execution_metrics['failed_tests']}")
lines.append("")
lines.append("## Metrics By Layer")
lines.append("| Layer | Suites (P/F/S) | Collected Tests | Failed Tests | Duration (s) |")
lines.append("|---|---:|---:|---:|---:|")
for item in by_layer_list:
  lines.append(
    "| "
    + item["layer"]
    + " | "
    + f"{item['suites_passed']}/{item['suites_failed']}/{item['suites_skipped']}"
    + " | "
    + str(item["collected_tests"])
    + " | "
    + str(item["failed_tests"])
    + " | "
    + str(item["duration_sec"])
    + " |"
  )
lines.append("")
lines.append("## Metrics By Service")
lines.append("| Service | Suites (P/F/S) | Collected Tests | Failed Tests | Duration (s) |")
lines.append("|---|---:|---:|---:|---:|")
for item in by_service_list:
  lines.append(
    "| "
    + item["service"]
    + " | "
    + f"{item['suites_passed']}/{item['suites_failed']}/{item['suites_skipped']}"
    + " | "
    + str(item["collected_tests"])
    + " | "
    + str(item["failed_tests"])
    + " | "
    + str(item["duration_sec"])
    + " |"
  )
lines.append("")
lines.append("## Failure Hotspots")
if not failed_tests_by_suite:
  lines.append("- None")
else:
  for suite, count in sorted(failed_tests_by_suite.items(), key=lambda kv: (-kv[1], kv[0])):
    lines.append(f"- {suite}: {count} failed tests")
lines.append("")
lines.append("## Infra Status")
lines.append(f"- Status: {summary['infra']['status']}")
lines.append(f"- compose ps: {summary['infra']['artifacts']['compose_ps']}")
lines.append(f"- compose config: {summary['infra']['artifacts']['compose_config']}")
lines.append(f"- compose all logs: {summary['infra']['artifacts']['compose_all_log']}")
lines.append(f"- service logs dir: {summary['infra']['artifacts']['services_logs_dir']}")
lines.append(f"- inspect dir: {summary['infra']['artifacts']['inspect_dir']}")
lines.append("")
lines.append("## Suite Results")
if not rows:
    lines.append("- No suites executed")
else:
    for row in rows:
        line = (
            f"- {row['label']}: {row['status']} "
            f"(layer={row['layer']}, type={row['suite_type']}, "
            f"collected={row['collected']}, duration={row['duration_sec']}s"
        )
        if row.get("failure_type"):
            line += f", failure_type={row['failure_type']}"
        line += ")"
        if row.get("reason"):
            line += f" - {row['reason']}"
        lines.append(line)

lines.append("")
lines.append("## Failed Tests (Reason + Traceback Excerpt)")
if not failed_tests:
    lines.append("- None")
else:
    for idx, item in enumerate(failed_tests, start=1):
        lines.append(f"### {idx}. {item['name']}")
        lines.append(f"- suite: {item['suite']}")
        lines.append(f"- kind: {item['kind']}")
        lines.append(f"- reason: {item['reason']}")
        if item["log"]:
            lines.append(f"- log: {item['log']}")
        if item["trace"]:
            lines.append("```text")
            lines.append(item["trace"])
            lines.append("```")
        lines.append("")

report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
PY

cp "$RUN_REPORT_FILE" "$REPORT_FILE"
cp "$RUN_SUMMARY_FILE" "$SUMMARY_FILE"

echo "Report written to: $REPORT_FILE"
echo "Summary written to: $SUMMARY_FILE"

aifinal_status=0
if [[ "$TEST_FAILURES" == "true" ]]; then
  aifinal_status=1
fi

if [[ $aifinal_status -ne 0 ]]; then
  echo "Full test suite finished with failures."
  exit 1
fi

echo "Full test suite passed."