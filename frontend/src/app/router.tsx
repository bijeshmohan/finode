// Every address the app answers. Inside the layout a session is guaranteed (SessionProvider); sign-in stands outside.
// Pages are placeholders until their step of the rebuild; real pages are loaded lazily as they arrive.
import { Navigate, Outlet, type RouteObject, useLocation } from "react-router";

import { EntryRoute } from "../features/entry/EntryRoute";
import { Home } from "../features/home/Home";
import { NotFound } from "../features/placeholder/NotFound";
import { TransactionsPage } from "../features/transactions/TransactionsPage";
import { Placeholder } from "../features/placeholder/Placeholder";
import { Forgot } from "../features/auth/Forgot";
import { Reset } from "../features/auth/Reset";
import { SignIn } from "../features/auth/SignIn";
import { SignUp } from "../features/auth/SignUp";
import { Layout } from "./Layout";
import { SessionProvider } from "./session";
import { ToastProvider } from "./toast";

const PAGES: [path: string, title: string][] = [
  ["/budget", "Budgets"],
  ["/accounts", "Accounts"],
  ["/categories", "Categories"],
  ["/people", "People"],
  ["/settings", "Settings"],
];

/** An old address of the web pages (/login, /signup), kept so bookmarks and mails still work. */
function MovedTo({ path }: { path: string }) {
  const { search } = useLocation();
  return <Navigate to={path + search} replace />;
}

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
  { path: "/sign-in", element: <SignIn /> },
  { path: "/login", element: <MovedTo path="/sign-in" /> },
  { path: "/sign-up", element: <SignUp /> },
  { path: "/signup", element: <MovedTo path="/sign-up" /> },
  { path: "/forgot", element: <Forgot /> },
  { path: "/reset", element: <Reset /> },
  {
    element: <SignedIn />,
    children: [
      {
        element: <Layout />,
        children: [
          { path: "/", element: <Home /> },
          { path: "/transactions", element: <TransactionsPage /> },
          { path: "/transactions/new", element: <EntryRoute /> },
          { path: "/transactions/:transactionId/edit", element: <EntryRoute /> },
          ...PAGES.map(([path, title]) => ({ path, element: <Placeholder title={title} /> })),
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
];
