// Every address the app answers. Inside the layout a session is guaranteed (SessionProvider); sign-in stands outside.
// Pages are placeholders until their step of the rebuild; real pages are loaded lazily as they arrive.
import { Navigate, Outlet, type RouteObject, useLocation } from "react-router";

import { EntryRoute } from "../features/entry/EntryRoute";
import { Home } from "../features/home/Home";
import { NotFound } from "../features/placeholder/NotFound";
import { TransactionsPage } from "../features/transactions/TransactionsPage";
import { AccountForm } from "../features/accounts/AccountForm";
import { AccountPage } from "../features/accounts/AccountPage";
import { AccountsPage } from "../features/accounts/AccountsPage";
import { GroupForm } from "../features/accounts/GroupForm";
import { BudgetPage } from "../features/budget/BudgetPage";
import { ComingUpPage } from "../features/budget/ComingUpPage";
import { GroupPage, OldGroupAddress } from "../features/budget/GroupPage";
import { MovePage } from "../features/budget/MovePage";
import { CategoriesPage } from "../features/categories/CategoriesPage";
import { CategoryForm } from "../features/categories/CategoryForm";
import { CategoryPage } from "../features/categories/CategoryPage";
import { OpeningForm } from "../features/people/OpeningForm";
import { PeoplePage } from "../features/people/PeoplePage";
import { PersonForm } from "../features/people/PersonForm";
import { PersonPage } from "../features/people/PersonPage";
import { RecurringForm, RuleAddress } from "../features/recurring/RecurringForm";
import { RecurringPage } from "../features/recurring/RecurringPage";
import { TagsPage } from "../features/tags/TagsPage";
import { Placeholder } from "../features/placeholder/Placeholder";
import { Forgot } from "../features/auth/Forgot";
import { Reset } from "../features/auth/Reset";
import { SignIn } from "../features/auth/SignIn";
import { SignUp } from "../features/auth/SignUp";
import { Layout } from "./Layout";
import { SessionProvider } from "./session";
import { ToastProvider } from "./toast";

const PAGES: [path: string, title: string][] = [["/settings", "Settings"]];

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
          { path: "/accounts", element: <AccountsPage /> },
          { path: "/accounts/new", element: <AccountForm /> },
          { path: "/accounts/new-group", element: <GroupForm /> },
          { path: "/accounts/:accountId/edit", element: <AccountForm /> },
          { path: "/budget", element: <BudgetPage /> },
          { path: "/budget/move", element: <MovePage /> },
          { path: "/budget/coming-up", element: <ComingUpPage /> },
          { path: "/tags", element: <TagsPage /> },
          { path: "/people", element: <PeoplePage /> },
          { path: "/people/new", element: <PersonForm /> },
          { path: "/people/:contactId", element: <PersonPage /> },
          { path: "/people/:contactId/edit", element: <PersonForm /> },
          { path: "/people/:contactId/opening", element: <OpeningForm /> },
          { path: "/people/:contactId/opening/:transactionId/edit", element: <OpeningForm /> },
          { path: "/recurring", element: <RecurringPage /> },
          { path: "/recurring/new", element: <RecurringForm /> },
          { path: "/recurring/:recurringId/edit", element: <RecurringForm /> },
          { path: "/recurring/:recurringId", element: <RuleAddress /> },
          { path: "/budget/groups/:categoryId", element: <GroupPage /> },
          { path: "/budget/group/:categoryId", element: <OldGroupAddress /> },
          { path: "/categories", element: <CategoriesPage /> },
          { path: "/categories/new", element: <CategoryForm /> },
          { path: "/categories/:categoryId", element: <CategoryPage /> },
          { path: "/categories/:categoryId/edit", element: <CategoryForm /> },
          { path: "/accounts/:accountId", element: <AccountPage /> },
          ...PAGES.map(([path, title]) => ({ path, element: <Placeholder title={title} /> })),
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
];
