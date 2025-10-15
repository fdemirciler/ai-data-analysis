import React, { useState } from "react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { useAuth } from "../context/AuthContext";
import { Github, Mail } from "lucide-react";
import { toast } from "sonner";

export default function AuthBox() {
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
    <div className="w-full max-w-md bg-white rounded-2xl shadow-xl p-6">
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="email" className="text-sm">Email</Label>
          <Input
            id="email"
            type="email"
            placeholder="Enter your email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="bg-input-background"
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="password" className="text-sm">Password</Label>
          <Input
            id="password"
            type="password"
            placeholder="Enter your password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="bg-input-background"
          />
        </div>

        {isLogin && (
          <div className="text-right">
            <button
              type="button"
              className="text-sm text-muted-foreground hover:text-foreground transition-colors"
              onClick={handleForgotPassword}
            >
              Forgot password?
            </button>
          </div>
        )}

        <Button 
          type="submit" 
          className="w-full shadow-lg hover:shadow-xl transition-all duration-200 hover:scale-[1.02] active:scale-[0.98]" 
          disabled={loading} 
          style={{ backgroundColor: '#7985c9' }}
        >
          {loading ? "Please wait..." : isLogin ? "Sign in" : "Create account"}
        </Button>
      </form>

      <div className="relative my-4">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-border"></div>
        </div>
        <div className="relative flex justify-center">
          <span className="bg-white px-4 text-sm text-muted-foreground">Or continue with</span>
        </div>
      </div>

      <div className="space-y-2">
        <Button 
          type="button" 
          variant="outline" 
          className="w-full shadow-md hover:shadow-lg transition-all duration-200 hover:scale-[1.02] active:scale-[0.98] hover:bg-gray-50" 
          onClick={handleGoogleSignIn}
        >
          <Mail className="mr-2 h-4 w-4" />
          Google
        </Button>
        <Button 
          type="button" 
          variant="outline" 
          className="w-full shadow-md hover:shadow-lg transition-all duration-200 hover:scale-[1.02] active:scale-[0.98] hover:bg-gray-50" 
          onClick={handleGithubSignIn}
        >
          <Github className="mr-2 h-4 w-4" />
          GitHub
        </Button>
      </div>

      <div className="mt-4 text-center">
        <p className="text-sm text-muted-foreground">
          {isLogin ? "Don't have an account? " : "Already have an account? "}
          <button type="button" onClick={() => setIsLogin(!isLogin)} className="text-primary hover:underline">
            {isLogin ? "Register now" : "Sign in"}
          </button>
        </p>
      </div>
    </div>
  );
}