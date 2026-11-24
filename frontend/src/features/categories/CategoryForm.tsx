// Adding or editing a category: its name, its icon and a note. An edit sends only what changed.
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { messageOf } from "../../api/messages";
import { useToast } from "../../app/toast";
import { Icon } from "../../components/Icon";
import { IconPicker } from "../../components/IconPicker";
import { LoadError } from "../../components/LoadError";
import look from "../../components/Page.module.css";
import form from "../../components/Forms.module.css";
import { useAddCategory } from "../../components/lines/queries";
import { type CategoryFormView, type CategoryUpdate, useCategoryChange, useCategoryForm } from "./queries";

function FormBody({ view, categoryId }: { view: CategoryFormView; categoryId: string | undefined }) {
  const toast = useToast();
  const navigate = useNavigate();
  const add = useAddCategory();
  const change = useCategoryChange();
  const remove = useCategoryChange();
  const editing = view.editing;
  const [name, setName] = useState(view.name);
  const [note, setNote] = useState(view.details ?? "");
  const [icon, setIcon] = useState<string | null>(view.icon ?? null);
  const [problem, setProblem] = useState<string | null>(null);
  const tab = view.kind === "earning" ? "income" : "expense";
  const back = editing && categoryId ? `/categories/${categoryId}` : `/categories?tab=${tab}`;

  const submit = () => {
    setProblem(null);
    const details = note.trim() || null;
    const failed = (e: unknown) => {
      setProblem(messageOf(e));
    };
    if (!editing) {
      if (!icon) {
        setProblem("Choose an icon");
        return;
      }
      add.mutate(
        { name: name.trim(), kind: view.kind, icon, details },
        {
          onSuccess: (made) => {
            toast("Category added");
            void navigate(`/categories/${made.id}`, { replace: true });
          },
          onError: failed,
        },
      );
      return;
    }
    const changes: CategoryUpdate = {};
    if (name.trim() !== view.name) changes.name = name.trim();
    if (details !== view.details) changes.details = details;
    if (icon && icon !== view.icon && !view.icon_fixed) changes.icon = icon;
    if (!categoryId || Object.keys(changes).length === 0) {
      void navigate(back);
      return;
    }
    change.mutate(
      { action: "update", id: categoryId, body: changes },
      {
        onSuccess: () => {
          toast("Category updated");
          void navigate(back);
        },
        onError: failed,
      },
    );
  };

  return (
    <>
      <Link className={look.back} to={back}>
        <Icon name="back" />
        {editing ? view.name : "Categories"}
      </Link>
      <h1 className={form.title}>{editing ? "Edit category" : "Add category"}</h1>
      <form
        className={form.form}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label>
          Name
          <input
            type="text"
            maxLength={40}
            required
            placeholder={view.kind === "spending" ? "e.g. Groceries" : "e.g. Salary"}
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </label>
        {!view.icon_fixed && (
          <IconPicker
            value={icon}
            onChange={(chosen) => {
              setIcon(chosen);
              setProblem(null);
            }}
          />
        )}
        <details className={form.note} open={view.details ? true : undefined}>
          <summary>{view.details ? "Note" : "+ Add a note"}</summary>
          <label>
            <input
              type="text"
              maxLength={200}
              aria-label="Notes"
              value={note}
              onChange={(event) => {
                setNote(event.target.value);
              }}
            />
          </label>
        </details>
        {problem && (
          <p className={form.error} role="alert">
            {problem}
          </p>
        )}
        <div>
          <button
            type="submit"
            className={form.primary}
            disabled={add.isPending || change.isPending}
            aria-busy={add.isPending || change.isPending}
          >
            {editing ? "Save changes" : "Add category"}
          </button>
        </div>
      </form>
      {editing && categoryId && (
        <section className={form.danger}>
          {remove.isError && (
            <p className={form.error} role="alert">
              {messageOf(remove.error)}
            </p>
          )}
          <button
            type="button"
            className={form.dangerButton}
            disabled={remove.isPending}
            onClick={() => {
              if (!window.confirm(`Delete category '${view.name}'?`)) return;
              remove.mutate(
                { action: "delete", id: categoryId },
                {
                  onSuccess: () => {
                    toast("Category deleted");
                    void navigate(`/categories?tab=${tab}`, { replace: true });
                  },
                },
              );
            }}
          >
            <Icon name="trash" />
            Delete category
          </button>
          <p className={form.dangerHint}>
            A category that was never used is removed for good. One with entries stays in your history and reports, but
            leaves your lists and pickers.
          </p>
        </section>
      )}
    </>
  );
}

/** /categories/new (?root=) and /categories/:categoryId/edit. */
export function CategoryForm() {
  const { categoryId } = useParams();
  const [params] = useSearchParams();
  const query: { category_id?: string; root?: string } = categoryId ? { category_id: categoryId } : {};
  const root = params.get("root");
  if (!categoryId && root) query.root = root;
  const view = useCategoryForm(query);
  if (view.isError) return <LoadError error={view.error} onRetry={() => void view.refetch()} />;
  if (!view.data) return <h1 className="sr-only">{categoryId ? "Edit category" : "Add category"}</h1>;
  return <FormBody key={JSON.stringify(query)} view={view.data} categoryId={categoryId} />;
}
