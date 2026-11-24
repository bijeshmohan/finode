import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CategoryIcon, categoryIconGroups, iconLabel } from "./CategoryIcon";

describe("CategoryIcon", () => {
  it("is decorative and drawn at 20 points", () => {
    const { container } = render(<CategoryIcon name="shopping-cart" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("width", "20");
    expect(svg?.innerHTML).toContain("circle");
  });

  it("is drawn at 16 points in a chip", () => {
    const { container } = render(<CategoryIcon name="gift" size={16} />);
    expect(container.querySelector("svg")).toHaveAttribute("width", "16");
  });

  it("says which icon it draws, for tests and styles", () => {
    const { container } = render(<CategoryIcon name="credit-card" />);
    expect(container.querySelector("svg")).toHaveAttribute("data-icon", "credit-card");
  });

  it("unknown icon draws the tag", () => {
    const unknown = render(<CategoryIcon name="rocket" />).container.querySelector("svg")?.innerHTML;
    const tag = render(<CategoryIcon name="tag" />).container.querySelector("svg")?.innerHTML;
    expect(unknown).toBe(tag);
    expect(tag).not.toBe("");
  });

  it("names an icon in words and lists the picker's groups", () => {
    expect(iconLabel("shopping-cart")).toBe("shopping cart");
    expect(categoryIconGroups.map((g) => g.name)).toEqual([
      "Food and home",
      "Getting around",
      "Health and family",
      "Fun and shopping",
      "Money",
    ]);
  });
});
