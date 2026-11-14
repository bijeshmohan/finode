// Choose a new password from the emailed link (reset.html). Opening the link sends nothing: mail scanners open links,
// and the token must only be spent when the person submits.
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Navigate, useNavigate, useSearchParams } from "react-router";
import { z } from "zod";

import { ApiError, data } from "../../api/client";
import { useApi } from "../../api/context";
import { AuthScreen } from "./AuthScreen";
import type { ForgotState } from "./Forgot";
import { FormError, Stack, SubmitButton, TextField } from "./fields";
import { codeOf, messageOf } from "../../api/messages";
import { MIN_PASSWORD_LENGTH, RULES } from "./rules";
import { WithOptions } from "./options";
import { useSubmitOnce } from "../../api/useSubmitOnce";
import { forgetPreviousSession } from "./session";

const PASSWORD_CHANGED = "Your password was changed. You are signed in.";

const form = z
  .object({
    password: z.string().min(MIN_PASSWORD_LENGTH, { message: RULES.short }),
    confirm_password: z.string(),
  })
  .refine((f) => f.password === f.confirm_password, { message: RULES.mismatch, path: ["confirm_password"] });
type Form = z.infer<typeof form>;

export function Reset() {
  const [params] = useSearchParams();
  const tokenHash = params.get("token_hash");
  return (
    <WithOptions>
      {(options) => {
        if (!options.reset_enabled) return <Navigate to="/sign-in" replace />;
        if (!tokenHash) {
          const state: ForgotState = { error: "That link is not valid. Ask for a new one." };
          return <Navigate to="/forgot" replace state={state} />;
        }
        return <ResetForm tokenHash={tokenHash} />;
      }}
    </WithOptions>
  );
}

function ResetForm({ tokenHash }: { tokenHash: string }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Form>({ resolver: zodResolver(form) });

  const reset = useMutation({
    mutationFn: (body: Form) => data(api.POST("/api/auth/reset", { body: { ...body, token_hash: tokenHash } })),
    onSuccess: async () => {
      forgetPreviousSession(queryClient);
      await navigate("/", { replace: true, state: { toast: PASSWORD_CHANGED } });
    },
    onError: async (error) => {
      if (codeOf(error) === "link-invalid") {
        const state: ForgotState = { error: messageOf(error) };
        await navigate("/forgot", { replace: true, state });
      } else if (error instanceof ApiError && error.status === 404) {
        await navigate("/sign-in", { replace: true });
      }
    },
  });
  const submit = useSubmitOnce(reset);

  return (
    <AuthScreen intro="Choose a new password.">
      <FormError message={reset.isError ? messageOf(reset.error) : null} />
      <Stack
        onSubmit={() => {
          void handleSubmit((body) => {
            submit(body);
          })();
        }}
      >
        <TextField
          label="New password"
          type="password"
          autoComplete="new-password"
          startHere
          registration={register("password")}
          error={errors.password?.message}
        />
        <TextField
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          registration={register("confirm_password")}
          error={errors.confirm_password?.message}
        />
        <SubmitButton pending={reset.isPending}>Change password</SubmitButton>
      </Stack>
    </AuthScreen>
  );
}
