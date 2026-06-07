#!/usr/bin/env bash
# Grafana panel validation harness.
# For each dashboard JSON, extracts every PromQL/LogQL expr, runs it against the
# live Grafana ds-proxy (/api/ds/query), and emits a TSV of results.
#
# Usage:
#   scripts/grafana_validation.sh           # write TSV to build/grafana_validation_results.tsv
#   scripts/grafana_validation.sh --stdout  # write TSV to stdout
#
# Exit code:
#   0 if no panels classified as BROKEN
#   1 otherwise
#
# Prereqs: Grafana + Prometheus running locally on http://localhost:3000.
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
DASH_DIR="${REPO_ROOT}/infra/grafana/dashboards"
GRAFANA="http://localhost:3000"
AUTH="admin:admin"

# Flag parsing — only one flag supported.
USE_STDOUT=0
if [[ "${1:-}" == "--stdout" ]]; then
  USE_STDOUT=1
elif [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  sed -n '2,15p' "$0"
  exit 0
fi

if [[ "$USE_STDOUT" -eq 1 ]]; then
  OUT_FILE=/dev/stdout
else
  OUT_DIR="${REPO_ROOT}/build"
  mkdir -p "$OUT_DIR"
  OUT_FILE="${OUT_DIR}/grafana_validation_results.tsv"
fi

# Discover the Prometheus + Loki datasource UIDs once (they vary across installs).
PROM_UID=$(curl -s -u "$AUTH" "$GRAFANA/api/datasources" \
  | python3 -c "import json,sys
ds=json.load(sys.stdin)
for d in ds:
    if d.get('type')=='prometheus':
        print(d['uid']); break")
LOKI_UID=$(curl -s -u "$AUTH" "$GRAFANA/api/datasources" \
  | python3 -c "import json,sys
ds=json.load(sys.stdin)
for d in ds:
    if d.get('type')=='loki':
        print(d['uid']); break")
echo "# Prometheus UID: $PROM_UID  Loki UID: $LOKI_UID" >&2

# Stream header + body into a temp file first so we can both write it out and
# parse it for the exit-code summary.
TMP_TSV=$(mktemp)
trap 'rm -f "$TMP_TSV"' EXIT
printf "dashboard\tpanel_title\tdatasource\tquery\tframes\tseries\tsample_value\tstatus\terror\n" > "$TMP_TSV"

run_promql() {
  local expr="$1"
  # Apply permissive substitutions for template variables so a single instant
  # query has a fighting chance of returning data.
  local q="$expr"
  q=$(printf '%s' "$q" \
    | sed -E 's/\$tier/.+/g; s/\$service/.+/g; s/\$severity/.+/g; s/\$worker/.+/g; s/\$category/.+/g; s/\$instance/.+/g; s/\$__rate_interval/5m/g; s/\$__interval/1m/g')
  python3 -c "
import json,urllib.request,urllib.error,base64,sys
expr=sys.argv[1]
uid=sys.argv[2]
body=json.dumps({'queries':[{'refId':'A','datasource':{'type':'prometheus','uid':uid},'expr':expr,'instant':True,'range':False,'maxDataPoints':100,'intervalMs':60000}],'from':'now-5m','to':'now'}).encode()
req=urllib.request.Request('${GRAFANA}/api/ds/query',data=body,method='POST')
req.add_header('Content-Type','application/json')
req.add_header('Authorization','Basic '+base64.b64encode(b'${AUTH}').decode())
try:
    r=urllib.request.urlopen(req,timeout=15)
    data=json.loads(r.read())
except urllib.error.HTTPError as e:
    print(json.dumps({'error':'HTTP '+str(e.code)+': '+e.read().decode()[:400]})); sys.exit(0)
except Exception as e:
    print(json.dumps({'error':'EXC: '+str(e)[:400]})); sys.exit(0)
res=data.get('results',{}).get('A',{})
err=res.get('error') or res.get('errorSource')
frames=res.get('frames') or []
series=0; sample=None
for f in frames:
    fields=f.get('schema',{}).get('fields',[])
    vals=f.get('data',{}).get('values',[])
    if vals and any(len(v)>0 for v in vals):
        series += 1
        for fd,col in zip(fields,vals):
            if fd.get('type')=='number' and col:
                sample=col[-1]; break
print(json.dumps({'frames':len(frames),'series':series,'sample':sample,'error':err}))
" "$q" "$PROM_UID"
}

shopt -s nullglob
for dash in "$DASH_DIR"/*.json; do
  name=$(basename "$dash" .json)
  echo "## $name" >&2
  panels_json=$(python3 - "$dash" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
out=[]
def walk(panels):
    for p in panels:
        t=p.get('title','(no title)')
        for tgt in (p.get('targets') or []):
            expr=tgt.get('expr') or tgt.get('rawSql') or tgt.get('query')
            if not expr: continue
            dst=(tgt.get('datasource') or {})
            dtype=dst.get('type') if isinstance(dst,dict) else 'prometheus'
            out.append({'title':t,'expr':expr,'dtype':dtype or 'prometheus'})
        if p.get('panels'): walk(p['panels'])
walk(d.get('panels',[]))
print(json.dumps(out))
PY
)
  n=$(printf '%s' "$panels_json" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
  echo "  $n targets" >&2
  printf '%s' "$panels_json" | python3 -c "
import json,sys
for i,p in enumerate(json.load(sys.stdin)):
    print(f\"{i}\t{p['title']}\t{p['dtype']}\t{p['expr']}\")
" | while IFS=$'\t' read -r idx title dtype expr; do
    if [[ "$dtype" == "loki" ]]; then
      printf "%s\t%s\t%s\t%s\t\t\t\tLOGQL-SKIP\t\n" "$name" "$title" "$dtype" "${expr//$'\n'/ }" >> "$TMP_TSV"
      continue
    fi
    result=$(run_promql "$expr")
    err=$(printf '%s' "$result" | python3 -c "import json,sys; r=json.load(sys.stdin); print(r.get('error') or '')")
    frames=$(printf '%s' "$result" | python3 -c "import json,sys; r=json.load(sys.stdin); print(r.get('frames',0))")
    series=$(printf '%s' "$result" | python3 -c "import json,sys; r=json.load(sys.stdin); print(r.get('series',0))")
    sample=$(printf '%s' "$result" | python3 -c "import json,sys; r=json.load(sys.stdin); print(r.get('sample') if r.get('sample') is not None else '')")
    if [[ -n "$err" ]]; then
      status="BROKEN"
    elif [[ "$series" -gt 0 ]]; then
      status="OK"
    else
      status="EMPTY-OK"
    fi
    flat_expr=$(printf '%s' "$expr" | tr '\n\t' '  ')
    flat_err=$(printf '%s' "$err" | tr '\n\t' '  ')
    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$name" "$title" "$dtype" "$flat_expr" "$frames" "$series" "$sample" "$status" "$flat_err" >> "$TMP_TSV"
  done
done

# Emit the TSV to the requested destination.
cat "$TMP_TSV" > "$OUT_FILE"
if [[ "$USE_STDOUT" -ne 1 ]]; then
  echo "DONE -> $OUT_FILE" >&2
fi

# Exit-code summary: 1 if any BROKEN rows, 0 otherwise.
BROKEN=$(awk -F'\t' 'NR>1 && $8=="BROKEN"' "$TMP_TSV" | wc -l | tr -d ' ')
echo "# BROKEN=$BROKEN" >&2
if [[ "$BROKEN" -gt 0 ]]; then
  exit 1
fi
exit 0
