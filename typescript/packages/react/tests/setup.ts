import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// `@testing-library/react`'s auto-cleanup only self-registers when it detects
// a global `afterEach` (i.e. `test.globals: true` in the vitest config). We
// don't enable globals, so register cleanup explicitly instead — otherwise
// each test's rendered DOM leaks into the next test in the same file.
afterEach(cleanup);
