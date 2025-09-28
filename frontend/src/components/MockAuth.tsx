import { useState } from "react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";

interface MockAuthProps {
  onLogin: (user: { name: string; email: string }) => void;
}

export function MockAuth({ onLogin }: MockAuthProps) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    if (email.trim() && name.trim()) {
      onLogin({ name: name.trim(), email: email.trim() });
    }
  };

  const handleDemoLogin = () => {
    onLogin({ name: "Demo User", email: "demo@example.com" });
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle>Data Analysis Chat</CardTitle>
          <CardDescription>
            Sign in to start analyzing your data
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-2">
              <label htmlFor="name" className="text-sm font-medium">
                Name
              </label>
              <Input
                id="name"
                type="text"
                placeholder="Enter your name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>
            
            <div className="space-y-2">
              <label htmlFor="email" className="text-sm font-medium">
                Email
              </label>
              <Input
                id="email"
                type="email"
                placeholder="Enter your email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <Button type="submit" className="w-full">
              Sign In
            </Button>
          </form>

          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-border" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-background px-2 text-muted-foreground">
                Or
              </span>
            </div>
          </div>

          <Button 
            variant="outline" 
            onClick={handleDemoLogin}
            className="w-full"
          >
            Continue with Demo Account
          </Button>

          <p className="text-xs text-muted-foreground text-center">
            This is a mock authentication for development purposes.
            In production, this would connect to Firebase Auth.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}