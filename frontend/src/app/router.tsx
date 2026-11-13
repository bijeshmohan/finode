// Every address the app answers. Inside the layout a session is guaranteed (SessionProvider); sign-in stands outside.
// Pages are placeholders until their step of the rebuild; real pages are loaded lazily as they arrive.
import { Outlet, type RouteObject } from "react-router";

import { NotFound } from "../features/placeholder/NotFound";
import { Placeholder } from "../features/placeholder/Placeholder";
import { SignInPlaceholder } from "../features/placeholder/SignInPlaceholder";
import { Layout } from "./Layout";
import { SessionProvider } from "./session";
import { ToastProvider } from "./toast";

const PAGES: [path: string, title: string][] = [
  ["/", "Home"],
  ["/budget", "Budgets"],
  ["/accounts", "Accounts"],
  ["/categories", "Categories"],
  ["/transactions", "Transactions"],
  ["/transactions/new", "New transaction"],
  ["/people", "People"],
  ["/settings", "Settings"],
];

function SignedIn() {
  return (
    <SessionProvider>
      <ToastProvider>
        <Outlet />
      </ToastProvider>
    </SessionProvider>
  );
}

export const routes: RouteObject[] = [
  { path: "/sign-in", element: <SignInPlaceholder /> },
  {
    element: <SignedIn />,
    children: [
      {
        element: <Layout />,
        children: [
          ...PAGES.map(([path, title]) => ({ path, element: <Placeholder title={title} /> })),
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
];
