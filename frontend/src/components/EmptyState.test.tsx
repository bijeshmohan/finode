import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("says what is missing and offers the next step", () => {
    render(<EmptyState title="Nothing recorded yet" action={<button type="button">Add one</button>} />);
    expect(screen.getByText("Nothing recorded yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add one" })).toBeInTheDocument();
  });
});
