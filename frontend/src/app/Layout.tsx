// The frame of every signed-in screen: on phones a top bar and a tab bar with the "+" docked in the middle; from 60rem a
// sidebar instead. Taken from app/templates/base.html and the App shell rules of app/static/style.css.
import { NavLink, Outlet } from "react-router";

import { Icon, type IconName } from "../components/Icon";
import styles from "./Layout.module.css";
import { NewEntryProvider, useNewEntryUrl } from "./newEntry";
import { Offline } from "./Offline";

interface Page {
  to: string;
  label: string;
  icon: IconName;
}

const HOME: Page = { to: "/", label: "Home", icon: "home" };
const BUDGETS: Page = { to: "/budget", label: "Budgets", icon: "budget" };
const ACCOUNTS: Page = { to: "/accounts", label: "Accounts", icon: "accounts" };
const CATEGORIES: Page = { to: "/categories", label: "Categories", icon: "tag" };
const TRANSACTIONS: Page = { to: "/transactions", label: "Transactions", icon: "list" };
const PEOPLE: Page = { to: "/people", label: "People", icon: "user" };

function PageLink({ page, className = "" }: { page: Page; className?: string }) {
  return (
    <NavLink to={page.to} end={page.to === "/"} className={className}>
      <Icon name={page.icon} />
      <span>{page.label}</span>
    </NavLink>
  );
}

export function Layout() {
  return (
    <NewEntryProvider>
      <Frame />
    </NewEntryProvider>
  );
}

function Frame() {
  const newEntry = useNewEntryUrl();
  return (
    <div>
      <header className={styles.topbar}>
        <NavLink to="/" className={styles.brand}>
          finode
        </NavLink>
        <NavLink to="/settings" className={styles.avatar} aria-label="Settings">
          <Icon name="gear" />
        </NavLink>
      </header>

      <aside className={styles.sidebar}>
        <NavLink to="/" className={styles.brand}>
          finode
        </NavLink>
        <NavLink to={newEntry} className={styles.sidebarNew}>
          <Icon name="plus" />
          <span>New transaction</span>
        </NavLink>
        <nav className={styles.sidenav} aria-label="Sidebar">
          {[HOME, BUDGETS, ACCOUNTS, CATEGORIES, TRANSACTIONS, PEOPLE].map((page) => (
            <PageLink key={page.to} page={page} />
          ))}
          <PageLink page={{ to: "/settings", label: "Settings", icon: "gear" }} className={styles.sidebarFoot} />
        </nav>
      </aside>

      <Offline />

      <main className={styles.main}>
        <Outlet />
      </main>

      <nav className={styles.tabbar} aria-label="Tab bar">
        <PageLink page={HOME} />
        <PageLink page={BUDGETS} />
        <NavLink to={newEntry} className={styles.fab} aria-label="New transaction">
          <Icon name="plus" />
        </NavLink>
        <PageLink page={ACCOUNTS} />
        <PageLink page={CATEGORIES} />
      </nav>
    </div>
  );
}
