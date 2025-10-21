import React, { useState } from "react";
import { Button } from "./ui/button";
import { Card, CardContent } from "./ui/card";
import { Separator } from "./ui/separator";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { useAuth } from "../context/AuthContext";
import { Github, Mail } from "lucide-react";
import { toast } from "sonner";

type AuthBoxProps = {
  showContinueAsGuest?: boolean;
  onContinueAsGuest?: () => void;
};

export default function AuthBox({ showContinueAsGuest = false, onContinueAsGuest }: AuthBoxProps) {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const { signIn, signUp, signInWithGoogle, signInWithGithub, sendPasswordReset } = useAuth();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      if (isLogin) {
        await signIn(email, password);
        toast.success("Successfully signed in!");
      } else {
        await signUp(email, password);
        toast.success("Account created successfully!");
      }
    } catch (error: any) {
      toast.error(error?.message || "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleSignIn = async () => {
    try {
      await signInWithGoogle();
      toast.success("Successfully signed in with Google!");
    } catch (error: any) {
      toast.error(error?.message || "An error occurred");
    }
  };

  const handleGithubSignIn = async () => {
    try {
      await signInWithGithub();
      toast.success("Successfully signed in with GitHub!");
    } catch (error: any) {
      toast.error(error?.message || "An error occurred");
    }
  };

  const handleForgotPassword = async () => {
    if (!email) {
      toast.message("Enter your email above and click 'Forgot password?' again.");
      return;
    }
    try {
      await sendPasswordReset(email);
      toast.success("Password reset email sent.");
    } catch (error: any) {
      toast.error(error?.message || "Failed to send reset email");
    }
  };

  return (
    <Card className="w-full border border-border/60 shadow-xl">
      <CardContent className="pt-4 pb-6 sm:pt-6 sm:pb-8 px-4 sm:px-8">
        <form onSubmit={handleSubmit} className="space-y-3 sm:space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="email" className="text-muted-foreground sm:text-base">
              Email
            </Label>
            <Input
              id="email"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="h-10 sm:h-11 border-border"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="password" className="text-muted-foreground sm:text-base">
              Password
            </Label>
            <Input
              id="password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="h-10 sm:h-11 border-border"
            />
          </div>

          {isLogin && (
            <div className="flex justify-end">
              <button
                type="button"
                className="text-xs sm:text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                onClick={handleForgotPassword}
              >
                Forgot password?
              </button>
            </div>
          )}

          <Button
            type="submit"
            className="w-full h-10 sm:h-11 text-sm sm:text-base shadow-lg hover:shadow-xl transition-all duration-200 hover:scale-[1.02] active:scale-[0.98]"
            size="lg"
            disabled={loading}
            style={{ backgroundColor: "#7985c9" }}
          >
            {loading ? "Please wait..." : isLogin ? "Sign in" : "Create account"}
          </Button>
        </form>

        <div className="flex items-center gap-3 sm:gap-4 mt-4 sm:mt-6">
          <Separator className="flex-1 bg-border/40" />
          <div className="px-3 text-xs sm:text-sm text-muted-foreground whitespace-nowrap">
            Or continue with
          </div>
          <Separator className="flex-1 bg-border/40" />
        </div>

        <div className="mt-4 sm:mt-6 space-y-2 sm:space-y-3">
          <Button
            type="button"
            variant="outline"
            className="w-full h-10 sm:h-11 font-semibold text-sm sm:text-base text-slate-500 cursor-pointer"
            size="lg"
            onClick={handleGoogleSignIn}
          >
            <Mail className="mr-2 h-4 w-4" />
            Google
          </Button>
          <Button
            type="button"
            variant="outline"
            className="w-full h-10 sm:h-11 font-semibold text-sm sm:text-base text-slate-500 cursor-pointer"
            size="lg"
            onClick={handleGithubSignIn}
          >
            <Github className="mr-2 h-4 w-4" />
            GitHub
          </Button>
        </div>

        <div className="mt-4 sm:mt-6 space-y-2 text-center text-xs sm:text-sm text-muted-foreground">
          <div>
            {isLogin ? "Don't have an account? " : "Already have an account? "}
            <button
              type="button"
              onClick={() => setIsLogin(!isLogin)}
              className="font-medium hover:underline cursor-pointer"
            >
              {isLogin ? "Register now" : "Sign in"}
            </button>
          </div>

          {showContinueAsGuest && (
            <button
              type="button"
              onClick={() => onContinueAsGuest?.()}
              className="font-medium text-indigo-600 hover:text-primary/80 transition-colors cursor-pointer underline-offset-4 hover:underline"
            >
              Continue as guest
            </button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
