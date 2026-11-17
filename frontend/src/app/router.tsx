// Every address the app answers. Inside the layout a session is guaranteed (SessionProvider); sign-in stands outside.
// A screen's `handle` names the browser tab (backend/finode/title.tsx); Home has none and is plain "finode".
import { Navigate, Outlet, type RouteObject, useLocation } from "react-router";

import { EntryRoute } from "../features/entry/EntryRoute";
import { Home } from "../features/home/Home";
import { NotFound } from "./NotFound";
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
import { ConsentPage } from "../features/consent/ConsentPage";
import { AssistantsPage } from "../features/settings/AssistantsPage";
import { DataPage } from "../features/settings/DataPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { RecurringForm, RuleAddress } from "../features/recurring/RecurringForm";
import { RecurringPage } from "../features/recurring/RecurringPage";
import { TagsPage } from "../features/tags/TagsPage";
import { Forgot } from "../features/auth/Forgot";
import { Reset } from "../features/auth/Reset";
import { SignIn } from "../features/auth/SignIn";
import { SignUp } from "../features/auth/SignUp";
import { Layout } from "./Layout";
import { SessionProvider } from "./session";
import { TabTitle } from "./title";
import { ToastProvider } from "./toast";

/** An old address (/login, /signup), kept so bookmarks and mails still work. */
function MovedTo({ path }: { path: string }) {
  const { search } = useLocation();
  return <Navigate to={path + search} replace />;
}

function SignedIn() {
  return (
    <SessionProvider>
      <Outlet />
    </SessionProvider>
  );
}

/** Toasts outlive the page that raised them, the sign-in screen included ("Your account was deleted"); the tab's title
 * follows every screen. */
function WithToasts() {
  return (
    <ToastProvider>
      <TabTitle>
        <Outlet />
      </TabTitle>
    </ToastProvider>
  );
}

export const routes: RouteObject[] = [
  {
    element: <WithToasts />,
    children: [
      { path: "/sign-in", element: <SignIn />, handle: { title: "Sign in" } },
      { path: "/login", element: <MovedTo path="/sign-in" /> },
      { path: "/sign-up", element: <SignUp />, handle: { title: "Sign up" } },
      { path: "/signup", element: <MovedTo path="/sign-up" /> },
      { path: "/forgot", element: <Forgot />, handle: { title: "Forgotten password" } },
      { path: "/reset", element: <Reset />, handle: { title: "Reset password" } },
      {
        element: <SignedIn />,
        children: [
          {
            element: <Layout />,
            children: [
              { path: "/", element: <Home /> },
              { path: "/transactions", element: <TransactionsPage />, handle: { title: "Transactions" } },
              { path: "/transactions/new", element: <EntryRoute />, handle: { title: "New transaction" } },
              {
                path: "/transactions/:transactionId/edit",
                element: <EntryRoute />,
                handle: { title: "Edit transaction" },
              },
              { path: "/accounts", element: <AccountsPage />, handle: { title: "Accounts" } },
              { path: "/accounts/new", element: <AccountForm />, handle: { title: "Add account" } },
              { path: "/accounts/new-group", element: <GroupForm />, handle: { title: "New group" } },
              { path: "/accounts/:accountId/edit", element: <AccountForm />, handle: { title: "Edit account" } },
              { path: "/budget", element: <BudgetPage />, handle: { title: "Budgets" } },
              { path: "/budget/move", element: <MovePage />, handle: { title: "Move money" } },
              { path: "/budget/coming-up", element: <ComingUpPage />, handle: { title: "Coming up" } },
              { path: "/tags", element: <TagsPage />, handle: { title: "Tags" } },
              { path: "/people", element: <PeoplePage />, handle: { title: "People" } },
              { path: "/people/new", element: <PersonForm />, handle: { title: "Add person" } },
              { path: "/people/:contactId", element: <PersonPage />, handle: { title: "People" } },
              { path: "/people/:contactId/edit", element: <PersonForm />, handle: { title: "Edit person" } },
              { path: "/people/:contactId/opening", element: <OpeningForm />, handle: { title: "Opening balance" } },
              {
                path: "/people/:contactId/opening/:transactionId/edit",
                element: <OpeningForm />,
                handle: { title: "Edit opening balance" },
              },
              { path: "/recurring", element: <RecurringPage />, handle: { title: "Recurring" } },
              { path: "/recurring/new", element: <RecurringForm />, handle: { title: "New recurring transaction" } },
              {
                path: "/recurring/:recurringId/edit",
                element: <RecurringForm />,
                handle: { title: "Edit recurring transaction" },
              },
              { path: "/recurring/:recurringId", element: <RuleAddress /> },
              { path: "/budget/groups/:categoryId", element: <GroupPage />, handle: { title: "Budgets" } },
              { path: "/budget/group/:categoryId", element: <OldGroupAddress /> },
              { path: "/categories", element: <CategoriesPage />, handle: { title: "Categories" } },
              { path: "/categories/new", element: <CategoryForm />, handle: { title: "Add category" } },
              { path: "/categories/:categoryId", element: <CategoryPage />, handle: { title: "Categories" } },
              { path: "/categories/:categoryId/edit", element: <CategoryForm />, handle: { title: "Edit category" } },
              { path: "/accounts/:accountId", element: <AccountPage />, handle: { title: "Accounts" } },
              { path: "/settings", element: <SettingsPage />, handle: { title: "Settings" } },
              { path: "/profile/data", element: <DataPage />, handle: { title: "Your data" } },
              { path: "/profile/assistants", element: <AssistantsPage />, handle: { title: "AI assistants" } },
              { path: "/oauth/consent", element: <ConsentPage />, handle: { title: "Connect an app" } },
              { path: "*", element: <NotFound />, handle: { title: "Page not found" } },
            ],
          },
        ],
      },
    ],
  },
];
