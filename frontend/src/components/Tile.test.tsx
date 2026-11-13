import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Tile } from "./Tile";

describe("Tile", () => {
  it("is a section named by its title", () => {
    render(<Tile title="Spending">rows</Tile>);
    expect(screen.getByRole("region", { name: "Spending" })).toHaveTextContent("rows");
  });
});
