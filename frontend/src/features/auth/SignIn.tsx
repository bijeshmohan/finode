// Sign in (login.html): email and password, then where the person was going (only inside the app), or Home.
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router";
import { z } from "zod";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import { AuthScreen } from "./AuthScreen";
import { FormError, Notice, Stack, SubmitButton, SwitchLine, TextField } from "./fields";
import { messageOf } from "../../api/messages";
import { useAuthOptions } from "./options";
import { safeNext } from "../../lib/safeNext";
import { useSubmitOnce } from "../../api/useSubmitOnce";
import { forgetPreviousSession } from "./session";

const form = z.object({ email: z.string().trim().min(1), password: z.string().min(1) });
type Form = z.infer<typeof form>;

export function SignIn() {
  const api = useApi();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const options = useAuthOptions();
  const { register, handleSubmit } = useForm<Form>({ resolver: zodResolver(form) });

  const signIn = useMutation({
    mutationFn: (body: Form) => data(api.POST("/api/auth/sign-in", { body })),
    onSuccess: async () => {
      forgetPreviousSession(queryClient);
      await navigate(safeNext(params.get("next")), { replace: true });
    },
  });
  const submit = useSubmitOnce(signIn);

  return (
    <AuthScreen intro="Sign in to your ledger.">
      {params.get("created") && <Notice>Account created. Please sign in.</Notice>}
      <FormError message={signIn.isError ? messageOf(signIn.error) : null} />
      <Stack
        onSubmit={() => {
          void handleSubmit((body) => {
            submit(body);
          })();
        }}
      >
        <TextField label="Email" type="email" autoComplete="username" startHere registration={register("email")} />
        <TextField
          label="Password"
          type="password"
          autoComplete="current-password"
          registration={register("password")}
        />
        <SubmitButton pending={signIn.isPending}>Sign in</SubmitButton>
      </Stack>
      {options.data?.reset_enabled && (
        <SwitchLine>
          <Link to="/forgot">Forgot your password?</Link>
        </SwitchLine>
      )}
      {options.data?.signup_enabled && (
        <SwitchLine>
          Have an invite code? <Link to="/sign-up">Create an account</Link>
        </SwitchLine>
      )}
    </AuthScreen>
  );
}
