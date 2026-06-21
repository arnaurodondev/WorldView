/**
 * components/alerts/__tests__/condition-editors.test.tsx — each editor emits the
 * structured condition (PLAN-0113 W4 T-4-04 / T-4-05).
 *
 * The editors compose the shared pickers (EntityPicker / InstrumentPicker /
 * MetricPicker) which hit the gateway. We MOCK those pickers with tiny stubs that
 * expose a "pick" button calling `onSelect` with a fixed entity/instrument, and a
 * stub MetricPicker that calls `onChange`. That isolates the EDITOR logic — the
 * `onChange(condition)` contract — from network plumbing. The pickers themselves
 * are covered separately (EntityPicker.test.tsx).
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ── Picker stubs ──────────────────────────────────────────────────────────────

vi.mock("@/components/common/EntityPicker", () => ({
  EntityPicker: ({
    label,
    value,
    onSelect,
  }: {
    label: string;
    value: { entityId: string; name: string } | null;
    onSelect: (e: { entityId: string; name: string }) => void;
  }) =>
    value ? (
      <div data-testid={`entity-${label}`}>{value.entityId}</div>
    ) : (
      <button
        type="button"
        data-testid={`pick-entity-${label}`}
        onClick={() => onSelect({ entityId: `ent-${label}`, name: label })}
      >
        pick {label}
      </button>
    ),
}));

vi.mock("@/components/common/InstrumentPicker", () => ({
  InstrumentPicker: ({
    label,
    value,
    onSelect,
  }: {
    label: string;
    value: { instrumentId: string } | null;
    onSelect: (i: { instrumentId: string; ticker: string; name: string }) => void;
  }) =>
    value ? (
      <div data-testid={`instrument-${label}`}>{value.instrumentId}</div>
    ) : (
      <button
        type="button"
        data-testid={`pick-instrument-${label}`}
        onClick={() => onSelect({ instrumentId: "i-aapl", ticker: "AAPL", name: "Apple" })}
      >
        pick {label}
      </button>
    ),
}));

vi.mock("@/components/alerts/MetricPicker", () => ({
  MetricPicker: ({ onChange }: { onChange: (k: string) => void }) => (
    <button type="button" data-testid="pick-metric" onClick={() => onChange("pe_ratio")}>
      pick metric
    </button>
  ),
}));

import { PriceCrossEditor } from "@/components/alerts/condition-editors/PriceCrossEditor";
import { FundamentalCrossEditor } from "@/components/alerts/condition-editors/FundamentalCrossEditor";
import { NewsVolumeEditor } from "@/components/alerts/condition-editors/NewsVolumeEditor";
import { NewsMomentumEditor } from "@/components/alerts/condition-editors/NewsMomentumEditor";
import { KgConnectionEditor } from "@/components/alerts/condition-editors/KgConnectionEditor";

describe("PriceCrossEditor", () => {
  it("emits {instrument_id, operator, value} once instrument + value are set", () => {
    const onChange = vi.fn();
    render(<PriceCrossEditor value={null} onChange={onChange} />);

    // Initially incomplete → null emitted.
    expect(onChange).toHaveBeenLastCalledWith(null);

    fireEvent.click(screen.getByTestId("pick-instrument-Instrument"));
    fireEvent.change(screen.getByLabelText(/Price level/i), { target: { value: "250" } });

    expect(onChange).toHaveBeenLastCalledWith({
      instrument_id: "i-aapl",
      operator: "above",
      value: 250,
    });
  });

  it("emits null for a non-positive price", () => {
    const onChange = vi.fn();
    render(<PriceCrossEditor value={null} onChange={onChange} />);
    fireEvent.click(screen.getByTestId("pick-instrument-Instrument"));
    fireEvent.change(screen.getByLabelText(/Price level/i), { target: { value: "0" } });
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  // PLAN-0113 QA fix (2026-06-20): a LIVE pick must report its display name up so
  // the wizard NL summary reads the ticker, not the raw UUID.
  it("reports the picked instrument's display name via onNamesChange", () => {
    const onNamesChange = vi.fn();
    render(
      <PriceCrossEditor value={null} onChange={vi.fn()} onNamesChange={onNamesChange} />,
    );
    fireEvent.click(screen.getByTestId("pick-instrument-Instrument"));
    // The stub picker selects {instrumentId:"i-aapl", ticker:"AAPL"}.
    expect(onNamesChange).toHaveBeenLastCalledWith({ "i-aapl": "AAPL" });
  });
});

describe("FundamentalCrossEditor", () => {
  it("emits {instrument_id, metric_key, operator, value}", () => {
    const onChange = vi.fn();
    render(<FundamentalCrossEditor value={null} onChange={onChange} />);

    fireEvent.click(screen.getByTestId("pick-instrument-Instrument"));
    fireEvent.click(screen.getByTestId("pick-metric"));
    fireEvent.change(screen.getByLabelText(/Metric threshold/i), { target: { value: "25" } });

    expect(onChange).toHaveBeenLastCalledWith({
      instrument_id: "i-aapl",
      metric_key: "pe_ratio",
      operator: "below",
      value: 25,
    });
  });
});

describe("NewsVolumeEditor", () => {
  it("emits {entity_id, window, threshold, keyword?}", () => {
    const onChange = vi.fn();
    render(<NewsVolumeEditor value={null} onChange={onChange} />);

    fireEvent.click(screen.getByTestId("pick-entity-Entity"));
    fireEvent.change(screen.getByLabelText(/Article count threshold/i), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText(/News keyword filter/i), { target: { value: "earnings" } });

    expect(onChange).toHaveBeenLastCalledWith({
      entity_id: "ent-Entity",
      window: "24h",
      threshold: 5,
      keyword: "earnings",
    });
  });

  it("omits keyword when blank", () => {
    const onChange = vi.fn();
    render(<NewsVolumeEditor value={null} onChange={onChange} />);
    fireEvent.click(screen.getByTestId("pick-entity-Entity"));
    // default threshold is "5"; entity now set → complete without keyword.
    expect(onChange).toHaveBeenLastCalledWith({
      entity_id: "ent-Entity",
      window: "24h",
      threshold: 5,
    });
  });
});

describe("NewsMomentumEditor", () => {
  it("emits {entity_id, window_hours, delta_pct, min_count}", () => {
    const onChange = vi.fn();
    render(<NewsMomentumEditor value={null} onChange={onChange} />);

    fireEvent.click(screen.getByTestId("pick-entity-Entity"));
    fireEvent.change(screen.getByLabelText(/Momentum delta percent/i), { target: { value: "50" } });
    fireEvent.change(screen.getByLabelText(/Minimum article count/i), { target: { value: "3" } });

    expect(onChange).toHaveBeenLastCalledWith({
      entity_id: "ent-Entity",
      window_hours: 24,
      delta_pct: 50,
      min_count: 3,
    });
  });
});

describe("KgConnectionEditor", () => {
  it("emits {source_entity_id, target_entity_id, max_hops} for two distinct entities", () => {
    const onChange = vi.fn();
    render(<KgConnectionEditor value={null} onChange={onChange} />);

    fireEvent.click(screen.getByTestId("pick-entity-From entity"));
    fireEvent.click(screen.getByTestId("pick-entity-To entity"));

    expect(onChange).toHaveBeenLastCalledWith({
      source_entity_id: "ent-From entity",
      target_entity_id: "ent-To entity",
      max_hops: 3,
    });
  });

  it("blocks node_a == node_b and emits null", () => {
    // Hydrate with an existing condition where both ids are identical so the
    // guard trips on mount.
    const onChange = vi.fn();
    render(
      <KgConnectionEditor
        value={{ source_entity_id: "x", target_entity_id: "x", max_hops: 2 }}
        onChange={onChange}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/must be different/i);
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});
