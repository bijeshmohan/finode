// Stands in for a page until its step of the rebuild (docs/superpowers/specs/2026-11-13-react-frontend-design.md).
import { useToday } from "../../app/session";

export function Placeholder({ title }: { title: string }) {
  return (
    <>
      <h1>{title}</h1>
      <p className="muted">
        This page is being rebuilt. Today is <span data-testid="today">{useToday()}</span>.
      </p>
    </>
  );
}
