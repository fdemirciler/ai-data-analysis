import React, { useEffect } from "react";
import { useAuth } from "../context/AuthContext";
import { useNavigate } from "react-router-dom";
import { Zap, Shield, Sparkles } from "lucide-react";
import AuthBox from "../components/AuthBox";
import { Card, CardContent } from "../components/ui/card";

export default function LandingPage() {
  const { user, loading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!loading && user && !user.isAnonymous) navigate("/chat", { replace: true });
  }, [loading, user, navigate]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div>Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(var(--vh,1vh)*100)] bg-gradient-to-br from-background to-muted relative overflow-x-hidden flex items-center">
      <svg className="absolute inset-0 w-full h-full" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path
              d="M 40 0 L 0 0 0 40"
              fill="none"
              stroke="currentColor"
              strokeWidth="0.5"
              className="text-muted-foreground/20"
            />
          </pattern>
          <pattern id="dots" width="20" height="20" patternUnits="userSpaceOnUse">
            <circle cx="2" cy="2" r="1" className="fill-muted-foreground/20" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid)" />
        <rect width="100%" height="100%" fill="url(#dots)" />

        <g className="text-muted-foreground/20" stroke="currentColor" strokeWidth="1.5" fill="none">
          <path
            d="M 100 200 Q 250 100 400 200 T 700 200"
            className="animate-pulse"
            style={{ animationDuration: "8s" }}
          />
          <path
            d="M 200 400 Q 350 300 500 400 T 800 400"
            className="animate-pulse"
            style={{ animationDuration: "10s", animationDelay: "1s" }}
          />
          <path
            d="M 150 600 Q 300 500 450 600 T 750 600"
            className="animate-pulse"
            style={{ animationDuration: "12s", animationDelay: "2s" }}
          />
        </g>
      </svg>

      <div className="container mx-auto px-4 sm:px-6 py-6 sm:py-8 relative z-10 w-full">
        <div className="grid lg:grid-cols-2 gap-6 sm:gap-8 lg:gap-12 items-start lg:items-end max-w-7xl mx-auto">
          <div className="space-y-6 sm:space-y-8">
            <div className="space-y-3 sm:space-y-4">

              <h1 className="text-indigo-400 text-3xl sm:text-4xl lg:text-5xl xl:text-6xl font-bold tracking-tight">
                Your AI Data Analyst
              </h1>
              <p className="text-sm sm:text-base lg:text-lg text-muted-foreground leading-relaxed max-w-xl">
                Transform your data into actionable insights with the power of artificial intelligence. Ask questions
                in natural language and get instant answers.
              </p>
            </div>

            <div className="grid gap-3 sm:gap-4">
              <Card className="shadow-sm border-border/60">
                <CardContent className="pt-4 sm:pt-6">
                  <div className="flex gap-3 sm:gap-4">
                    <div className="flex-shrink-0">
                      <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                        <Zap className="w-5 h-5 sm:w-6 sm:h-6 text-blue-600 dark:text-blue-400" />
                      </div>
                    </div>
                    <div className="space-y-1 min-w-0">
                      <h3 className="text-slate-500 font-semibold text-sm sm:text-base">
                        Get instant insights from your data
                      </h3>
                      <p className="text-xs sm:text-sm text-muted-foreground">
                        Upload your files and start asking questions. Our AI understands your data and provides clear,
                        accurate answers in seconds.
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="shadow-sm border-border/60">
                <CardContent className="pt-4 sm:pt-6">
                  <div className="flex gap-3 sm:gap-4">
                    <div className="flex-shrink-0">
                      <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-lg bg-green-100 dark:bg-green-900/30 flex items-center justify-center">
                        <Shield className="w-5 h-5 sm:w-6 sm:h-6 text-green-600 dark:text-green-400" />
                      </div>
                    </div>
                    <div className="space-y-1 min-w-0">
                      <h3 className="text-slate-500 font-semibold text-sm sm:text-base">Privacy focused</h3>
                      <p className="text-xs sm:text-sm text-muted-foreground">
                        Your files and data are automatically deleted after 1 day. We prioritize your privacy and security
                        above all else.
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="shadow-sm border-border/60">
                <CardContent className="pt-4 sm:pt-6">
                  <div className="flex gap-3 sm:gap-4">
                    <div className="flex-shrink-0">
                      <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-lg bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center">
                        <Sparkles className="w-5 h-5 sm:w-6 sm:h-6 text-purple-600 dark:text-purple-400" />
                      </div>
                    </div>
                    <div className="space-y-1 min-w-0">
                      <h3 className="text-slate-500 font-semibold text-sm sm:text-base">Powered by Gemini AI</h3>
                      <p className="text-xs sm:text-sm text-muted-foreground">
                        Leveraging cutting-edge AI technology for intelligent, context-aware data analysis.
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>

          <div className="flex justify-center lg:justify-end">
            <div className="w-full max-w-md">
              <AuthBox
                showContinueAsGuest={Boolean(user?.isAnonymous)}
                onContinueAsGuest={() => navigate("/chat")}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
