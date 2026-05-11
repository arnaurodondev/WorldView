/**
 * __tests__/form.test.tsx — Unit tests for Form primitive (PLAN-0059 F-2)
 *
 * WHY THIS EXISTS: The Form/FormField/FormItem/FormControl/FormMessage wrappers
 * are the a11y glue layer between RHF errors and the DOM. These tests verify
 * that:
 *   1. aria-invalid is applied to the input when the field has an error.
 *   2. FormMessage renders as role="alert" (screen-reader announcement).
 *   3. aria-describedby on the input points to the FormMessage element.
 *   4. The above are absent when the field is clean (no false positives).
 *
 * DATA SOURCE: No S9 calls — pure component tests.
 * DESIGN REFERENCE: PLAN-0059 F-2 BP-330 fix.
 */

import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";

// ── Test schema and component ──────────────────────────────────────────────

const schema = z.object({
  email: z.string().email("Invalid email address"),
  name: z.string().min(1, "Name is required"),
});

type TestValues = z.infer<typeof schema>;

/**
 * TestForm — minimal RHF form that exercises all form primitives.
 * Submitting with empty/invalid values triggers Zod validation errors.
 */
function TestForm({ onSubmit = () => {} }: { onSubmit?: (v: TestValues) => void }) {
  const form = useForm<TestValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", name: "" },
    // WHY "onSubmit" mode (default): errors only appear after the user tries
    // to submit. This is the expected UX for a compact finance modal form.
  });

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)}>
        <FormField
          control={form.control}
          name="email"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Email</FormLabel>
              <FormControl>
                <Input placeholder="user@example.com" {...field} />
              </FormControl>
              <FormDescription>Your email address</FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Name</FormLabel>
              <FormControl>
                <Input placeholder="Full name" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <button type="submit">Submit</button>
      </form>
    </Form>
  );
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe("Form — aria-invalid", () => {
  it("input has no aria-invalid when field is clean (initial state)", () => {
    render(<TestForm />);
    const emailInput = screen.getByPlaceholderText("user@example.com");
    // WHY check absence: aria-invalid="false" is semantically wrong — the
    // attribute should be absent when the field is valid, not set to "false".
    expect(emailInput).not.toHaveAttribute("aria-invalid");
  });

  it("input gets aria-invalid after failed submit on required field", async () => {
    const user = userEvent.setup();
    render(<TestForm />);
    await user.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => {
      const nameInput = screen.getByPlaceholderText("Full name");
      expect(nameInput).toHaveAttribute("aria-invalid", "true");
    });
  });

  it("email input gets aria-invalid when email format is invalid", async () => {
    const user = userEvent.setup();
    render(<TestForm />);
    await user.type(screen.getByPlaceholderText("user@example.com"), "notanemail");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => {
      const emailInput = screen.getByPlaceholderText("user@example.com");
      expect(emailInput).toHaveAttribute("aria-invalid", "true");
    });
  });

  it("aria-invalid is removed when field is corrected", async () => {
    const user = userEvent.setup();
    render(<TestForm />);
    // First trigger the error.
    await user.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => {
      expect(screen.getByPlaceholderText("Full name")).toHaveAttribute("aria-invalid", "true");
    });
    // Now fix it — type a valid name.
    await user.type(screen.getByPlaceholderText("Full name"), "Alice");
    await waitFor(() => {
      expect(screen.getByPlaceholderText("Full name")).not.toHaveAttribute("aria-invalid");
    });
  });
});

describe("Form — FormMessage", () => {
  it("FormMessage shows error text after failed submit", async () => {
    const user = userEvent.setup();
    render(<TestForm />);
    await user.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => {
      expect(screen.getByText("Name is required")).toBeInTheDocument();
    });
  });

  it("FormMessage has role='alert' so screen readers announce it", async () => {
    const user = userEvent.setup();
    render(<TestForm />);
    await user.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => {
      // WHY getAllByRole: both email AND name fields have errors after blank submit,
      // so there are two role="alert" elements. We just need to confirm alerts exist.
      const alerts = screen.getAllByRole("alert");
      expect(alerts.length).toBeGreaterThan(0);
      // Verify at least one alert contains the name error.
      const hasNameError = alerts.some((el) =>
        el.textContent?.includes("Name is required"),
      );
      expect(hasNameError).toBe(true);
    });
  });

  it("FormMessage shows the Zod error message verbatim", async () => {
    const user = userEvent.setup();
    render(<TestForm />);
    await user.type(screen.getByPlaceholderText("user@example.com"), "bad");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => {
      expect(screen.getByText("Invalid email address")).toBeInTheDocument();
    });
  });

  it("FormMessage is absent when field is valid", () => {
    render(<TestForm />);
    // No submit yet — there should be no alert in the DOM.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("Form — aria-describedby", () => {
  it("aria-describedby includes FormDescription id when no error", () => {
    render(<TestForm />);
    const emailInput = screen.getByPlaceholderText("user@example.com");
    const describedBy = emailInput.getAttribute("aria-describedby") ?? "";
    // The description paragraph should be in the dom with a matching id.
    const description = screen.getByText("Your email address");
    expect(describedBy).toContain(description.id);
  });

  it("aria-describedby includes FormMessage id after error", async () => {
    const user = userEvent.setup();
    render(<TestForm />);
    await user.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => {
      const emailInput = screen.getByPlaceholderText("user@example.com");
      const describedBy = emailInput.getAttribute("aria-describedby") ?? "";
      const errorMsg = screen.getByText("Invalid email address");
      expect(describedBy).toContain(errorMsg.id);
    });
  });
});

describe("Form — FormLabel", () => {
  it("FormLabel has htmlFor pointing to the input id", () => {
    render(<TestForm />);
    const emailInput = screen.getByPlaceholderText("user@example.com");
    const label = screen.getByText("Email");
    expect(label).toHaveAttribute("for", emailInput.id);
  });
});
