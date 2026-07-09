/**
 * lib/portfolio/mode-flag.ts — Portfolio Simple-mode rollout gate (PLAN-0122 W-A).
 *
 * WHY THIS EXISTS: PRD-0122 takes the portfolio page public with a "Simple"
 * default in front of today's power-user "Advanced" layout. That flip is risky
 * (it changes what every user sees), so we stage it behind a single build-time
 * constant instead of flipping the default the moment the hook lands.
 *
 * WHY A LITERAL CONSTANT (not an env var / feature-flag service): the rollout is
 * a one-line, code-reviewed edit — there is no need for runtime configurability,
 * and a literal keeps the value statically analysable (dead-code elimination,
 * type narrowing) and trivially greppable. Flipping it is a deliberate PR, not a
 * dashboard toggle that could silently change production.
 *
 * ROLLOUT SEQUENCE (PRD-0122 §10):
 *   • W-A (this wave): `false`. An unset user still resolves to **Advanced**
 *     (today's behaviour), so production is byte-identical while we wire the
 *     mode gate and prove parity with `test_advanced_mode_is_todays_layout`.
 *   • W-B: flip to `true` — Simple becomes the public default — but ONLY after
 *     the Advanced-snapshot + Simple specs are green and the existing e2e specs
 *     are forced into Advanced (R19).
 *
 * ROLLBACK: set this back to `false`. Because the mode is a pure render gate
 * (localStorage + URL, no data migration), that instantly returns every user
 * who never made an explicit choice to today's Advanced layout.
 */

// WHY exported as a top-level const (not inside a function): consumers read it at
// module scope so bundlers can inline/eliminate branches, and `usePortfolioMode`
// can use it directly as the default-mode source of truth.
export const PORTFOLIO_SIMPLE_DEFAULT = false;
