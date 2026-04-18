/**
 * vitest.setup.ts — Global test setup
 *
 * WHY THIS EXISTS: Imports @testing-library/jest-dom which extends Vitest's
 * expect() with DOM-specific matchers like toBeInTheDocument(), toHaveValue(),
 * toBeVisible(), etc. Without this, React Testing Library tests would need to
 * use lower-level querySelector() checks which are more brittle.
 */
import "@testing-library/jest-dom";
