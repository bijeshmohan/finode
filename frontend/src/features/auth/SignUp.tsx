// Invite-only sign-up (signup.html): the same checks and words as the web page; the server checks everything again.
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, Navigate, useNavigate } from "react-router";
import { z } from "zod";

import { ApiError, data } from "../../api/client";
import { useApi } from "../../api/context";
import { AuthScreen } from "./AuthScreen";
import { CheckField, FormError, Stack, SubmitButton, SwitchLine, TextField } from "./fields";
import { messageOf } from "../../api/messages";
import { MIN_PASSWORD_LENGTH, RULES } from "./rules";
import { WithOptions } from "./options";
import { forgetPreviousSession, useSubmitOnce } from "./session";
import { TestNotice } from "./TestNotice";

const TICK = "Please read the notice and tick the box to continue.";

function schema(testNotice: boolean) {
  return z
    .object({
      email: z.string().trim().includes("@", { message: RULES.email }),
      password: z.string().min(MIN_PASSWORD_LENGTH, { message: RULES.short }),
      confirm_password: z.string(),
      invite_code: z.string(), // checked by the server alone ("Invalid invite code.")
      accept: z.boolean(),
    })
    .refine((form) => form.password === form.confirm_password, { message: RULES.mismatch, path: ["confirm_password"] })
    .refine((form) => !testNotice || form.accept, { message: TICK, path: ["accept"] });
}
type Form = z.infer<ReturnType<typeof schema>>;

export function SignUp() {
  return (
    <WithOptions>
      {(options) =>
        options.signup_enabled ? <SignUpForm testNotice={options.test_notice} /> : <Navigate to="/sign-in" replace />
      }
    </WithOptions>
  );
}

function SignUpForm({ testNotice }: { testNotice: boolean }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Form>({ resolver: zodResolver(schema(testNotice)), defaultValues: { accept: false } });

  const signUp = useMutation({
    mutationFn: (body: Form) => data(api.POST("/api/auth/sign-up", { body })),
    onSuccess: async ({ signed_in }) => {
      if (!signed_in) {
        await navigate("/sign-in?created=1", { replace: true });
        return;
      }
      forgetPreviousSession(queryClient);
      await navigate("/", { replace: true });
    },
    onError: async (error) => {
      // Sign-up was switched off after this screen opened.
      if (error instanceof ApiError && error.status === 404) await navigate("/sign-in", { replace: true });
    },
  });
  const submit = useSubmitOnce(signUp);

  return (
    <AuthScreen intro="Create an account. You need an invite code.">
      <FormError message={signUp.isError ? messageOf(signUp.error) : null} />
      <Stack
        onSubmit={() => {
          void handleSubmit(submit)();
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
        <TextField
          label="Password"
          type="password"
          autoComplete="new-password"
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
        <TextField
          label="Invite code"
          type="password"
          autoComplete="off"
          registration={register("invite_code")}
          error={errors.invite_code?.message}
        />
        {testNotice && (
          <>
            <TestNotice />
            <CheckField
              label="I understand this is a test and have read the notice above."
              registration={register("accept")}
              error={errors.accept?.message}
            />
          </>
        )}
        <SubmitButton pending={signUp.isPending}>Create account</SubmitButton>
      </Stack>
      <SwitchLine>
        Already have an account? <Link to="/sign-in">Sign in</Link>
      </SwitchLine>
    </AuthScreen>
  );
}
