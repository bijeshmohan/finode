import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { Row } from "./Row";

describe("Row", () => {
  it("shows money in green with a plus", () => {
    render(<Row title="Salary" figure="50,000.00" figureTone="in" />);
    const figure = screen.getByText("+50,000.00");
    expect(figure.className).toMatch(/in/);
  });

  it("shows a real negative in red and ordinary amounts plain", () => {
    render(
      <>
        <Row title="Card" figure="−1,200.00" figureTone="out" />
        <Row title="Groceries" figure="300.00" />
      </>,
    );
    expect(screen.getByText("−1,200.00").className).toMatch(/out/);
    expect(screen.getByText("300.00").className).not.toMatch(/in|out/);
  });

  it("is a link when it leads somewhere", () => {
    render(
      <MemoryRouter>
        <Row title="HDFC" detail="Bank" to="/accounts/1" />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /HDFC/ })).toHaveAttribute("href", "/accounts/1");
  });

  it("is a button when it opens something", () => {
    const open = vi.fn();
    render(<Row title="Coffee" onClick={open} />);
    screen.getByRole("button", { name: /Coffee/ }).click();
    expect(open).toHaveBeenCalledOnce();
  });
});
