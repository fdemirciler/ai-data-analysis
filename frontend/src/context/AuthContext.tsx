import React, { createContext, useContext, useEffect, useState } from "react";
import { auth } from "../lib/firebase";
import { onIdTokenChanged, signInAnonymously, User } from "firebase/auth";

interface AuthState {
  user: User | null;
  idToken: string | null;
  loading: boolean;
}

const AuthContext = createContext<AuthState>({ user: null, idToken: null, loading: true });

export const AuthProvider: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [idToken, setIdToken] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let unsub = () => {};

    async function init() {
      try {
        // Ensure we have a user
        if (!auth.currentUser) {
          await signInAnonymously(auth);
        }
      } catch (_) {
        // ignore
      }

      unsub = onIdTokenChanged(auth, async (u) => {
        setUser(u);
        if (u) {
          const tok = await u.getIdToken();
          setIdToken(tok);
        } else {
          setIdToken(null);
        }
        setLoading(false);
      });
    }

    init();
    return () => unsub();
  }, []);

  return (
    <AuthContext.Provider value={{ user, idToken, loading }}>
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth() {
  return useContext(AuthContext);
}
