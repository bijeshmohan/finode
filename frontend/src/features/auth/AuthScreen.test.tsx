import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuthScreen } from "./AuthScreen";

describe("AuthScreen", () => {
  it("shows the brand, the intro and the form, and no tab bar", () => {
    render(<AuthScreen intro="Sign in to your ledger.">form</AuthScreen>);
    expect(screen.getByRole("heading", { name: "finode" })).toBeInTheDocument();
    expect(screen.getByText("Sign in to your ledger.")).toBeInTheDocument();
    expect(screen.getByText("form")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });
});
