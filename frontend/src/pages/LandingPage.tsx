import React, { useEffect } from "react";
import { useAuth } from "../context/AuthContext";
import { useNavigate } from "react-router-dom";
import { Zap, Shield, Sparkles } from "lucide-react";
import AuthBox from "../components/AuthBox";
import { Button } from "../components/ui/button";

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
    <div className="h-dvh flex overflow-hidden bg-gradient-to-br from-purple-100 via-blue-100 to-pink-100">
  <div className="hidden lg:flex lg:w-1/2 h-full relative p-8 flex-col justify-center overflow-y-auto">
    <div className="relative z-10 max-w-xl mx-auto -mt-14">
      <div className="mb-6">
        <h1 className="mb-4 pb-2 text-3xl xl:text-6xl bg-gradient-to-r from-blue-500 to-purple-400 bg-clip-text text-transparent leading-tight">
          Your AI Data Analyst
        </h1>
        <p className="text-slate-700 text-sm md:text-base text-justify">
          Transform your data into actionable insights with the power of artificial intelligence. Ask questions in natural language and get instant answers.
        </p>
      </div>


          <div className="space-y-3">
            <div className="flex items-start gap-3 bg-white/80 backdrop-blur-sm p-4 rounded-xl">
              <div className="flex-shrink-0 w-10 h-10 bg-gradient-to-br from-purple-400 to-blue-400 rounded-lg flex items-center justify-center">
                <Zap className="h-5 w-5 text-white" />
              </div>
              <div>
                <h3 className="mb-1 text-sm font-medium text-slate-800">Get instant insights from your data</h3>
                <p className="text-xs text-slate-600">
                  Upload your files and start asking questions. Our AI understands your data and provides clear, accurate answers in seconds.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 bg-white/80 backdrop-blur-sm p-4 rounded-xl">
              <div className="flex-shrink-0 w-10 h-10 bg-gradient-to-br from-blue-400 to-pink-400 rounded-lg flex items-center justify-center">
                <Shield className="h-5 w-5 text-white" />
              </div>
              <div>
                <h3 className="mb-1 text-sm font-medium text-slate-800">Privacy focused</h3>
                <p className="text-xs text-slate-600">
                  Your files and data are automatically deleted after 1 day. We prioritize your privacy and security above all else.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 bg-white/80 backdrop-blur-sm p-4 rounded-xl">
              <div className="flex-shrink-0 w-10 h-10 bg-gradient-to-br from-pink-400 to-purple-400 rounded-lg flex items-center justify-center">
                <Sparkles className="h-5 w-5 text-white" />
              </div>
              <div>
                <h3 className="mb-1 text-sm font-medium text-slate-800">Powered by Gemini AI</h3>
                <p className="text-xs text-slate-600">
                  Leveraging cutting-edge AI technology for intelligent, context-aware data analysis.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="w-full lg:w-1/2 h-full flex items-center justify-center p-4 lg:p-6 overflow-hidden">
        <div className="w-full max-w-md">
          <div className="lg:hidden mb-8 text-center">
            <h1 className="mb-2">Your AI Data Analyser</h1>
            <p className="text-muted-foreground">Transform your data into actionable insights</p>
          </div>

          <AuthBox />

          {user?.isAnonymous && (
  <div className="mt-4 text-center">
    <Button 
      onClick={() => navigate("/chat")} 
      className="shadow-lg hover:shadow-xl transition-all duration-200 hover:scale-[1.02] active:scale-[0.98]"
      style={{ backgroundColor: '#6f7cc9' }}
    >
      Continue as guest
    </Button>
  </div>
)}
        </div>
      </div>
    </div>
  );
}