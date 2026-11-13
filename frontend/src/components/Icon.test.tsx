import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Icon } from "./Icon";

describe("Icon", () => {
  it("is decorative by default", () => {
    const { container } = render(<Icon name="home" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg?.innerHTML).toContain("M3 10.5 12 3l9 7.5");
  });

  it("is labelled when given a label", () => {
    const { getByRole } = render(<Icon name="bell" label="To do" />);
    expect(getByRole("img", { name: "To do" })).toBeInTheDocument();
  });
});
