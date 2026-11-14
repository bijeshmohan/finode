// Forgotten password (forgot.html): ask for a reset link. The answer is the same whether or not the address has an
// account, so the screen cannot be used to find out who does.
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, Navigate, useLocation, useNavigate } from "react-router";
import { z } from "zod";

import { ApiError, data } from "../../api/client";
import { useApi } from "../../api/context";
import { AuthScreen } from "./AuthScreen";
import { FormError, Notice, Stack, SubmitButton, SwitchLine, TextField } from "./fields";
import { messageOf } from "../../api/messages";
import { RULES } from "./rules";
import { WithOptions } from "./options";
import { useSubmitOnce } from "../../api/useSubmitOnce";

const form = z.object({ email: z.string().trim().includes("@", { message: RULES.email }) });
type Form = z.infer<typeof form>;

/** What another screen can hand over when it sends the person here (a reset link that no longer works). */
export interface ForgotState {
  error?: string;
}

export function Forgot() {
  return (
    <WithOptions>
      {(options) => (options.reset_enabled ? <ForgotForm /> : <Navigate to="/sign-in" replace />)}
    </WithOptions>
  );
}

function ForgotForm() {
  const api = useApi();
  const handedOver = (useLocation().state as ForgotState | null)?.error ?? null;
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Form>({ resolver: zodResolver(form) });
  const navigate = useNavigate();
  const send = useMutation({
    mutationFn: (body: Form) => data(api.POST("/api/auth/forgot", { body })),
    onError: async (error) => {
      // Reset was switched off after this screen opened.
      if (error instanceof ApiError && error.status === 404) await navigate("/sign-in", { replace: true });
    },
  });
  const submit = useSubmitOnce(send);

  return (
    <AuthScreen
      intro={
        send.isSuccess ? undefined : "Enter your email address and we will send you a link to choose a new password."
      }
    >
      {send.isSuccess ? (
        <Notice>
          If there is an account for {send.variables.email}, an email with a link to choose a new password is on its
          way. The link works for an hour. Check your spam folder if it does not arrive.
        </Notice>
      ) : (
        <>
          <FormError message={send.isError ? messageOf(send.error) : handedOver} />
          <Stack
            onSubmit={() => {
              void handleSubmit((body) => {
                submit(body);
              })();
            }}
          >
            <TextField
              label="Email"
              type="email"
              autoComplete="username"
              startHere
              registration={register("email")}
              error={errors.email?.message}
            />
            <SubmitButton pending={send.isPending}>Send the link</SubmitButton>
          </Stack>
        </>
      )}
      <SwitchLine>
        <Link to="/sign-in">Back to sign in</Link>
      </SwitchLine>
    </AuthScreen>
  );
}
