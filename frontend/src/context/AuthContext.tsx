import React, { createContext, useContext, useEffect, useState } from "react";
import { auth } from "../lib/firebase";
import {
  onIdTokenChanged,
  signInAnonymously,
  User,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  GoogleAuthProvider,
  GithubAuthProvider,
  signInWithPopup,
  signOut as firebaseSignOut,
  setPersistence,
  browserLocalPersistence,
  sendPasswordResetEmail,
} from "firebase/auth";
import { ensureUserProfile } from "../services/firestore";

interface AuthContextValue {
  user: User | null;
  idToken: string | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  signInWithGithub: () => Promise<void>;
  sendPasswordReset: (email: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  idToken: null,
  loading: true,
  signIn: async () => {},
  signUp: async () => {},
  signInWithGoogle: async () => {},
  signInWithGithub: async () => {},
  sendPasswordReset: async () => {},
  signOut: async () => {},
});

export const AuthProvider: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [idToken, setIdToken] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let unsub = () => {};

    async function init() {
      try {
        await setPersistence(auth, browserLocalPersistence);
        if (!auth.currentUser) {
          await signInAnonymously(auth);
        }
      } catch (_) {}

      unsub = onIdTokenChanged(auth, async (u) => {
        setUser(u);
        if (u) {
          const tok = await u.getIdToken();
          setIdToken(tok);
          await ensureUserProfile(u.uid, { email: u.email || "", displayName: u.displayName || "" });
        } else {
          setIdToken(null);
        }
        setLoading(false);
      });
    }

    init();
    return () => unsub();
  }, []);

  const signIn = async (email: string, password: string) => {
    const cred = await signInWithEmailAndPassword(auth, email, password);
    if (cred.user && !cred.user.isAnonymous) {
      await ensureUserProfile(cred.user.uid, { email: cred.user.email || "", displayName: cred.user.displayName || "" });
    }
  };

  const signUp = async (email: string, password: string) => {
    const cred = await createUserWithEmailAndPassword(auth, email, password);
    if (cred.user) {
      await ensureUserProfile(cred.user.uid, { email: cred.user.email || "", displayName: cred.user.displayName || "" });
    }
  };

  const signInWithGoogle = async () => {
    const provider = new GoogleAuthProvider();
    const cred = await signInWithPopup(auth, provider);
    if (cred.user) {
      await ensureUserProfile(cred.user.uid, { email: cred.user.email || "", displayName: cred.user.displayName || "" });
    }
  };

  const signInWithGithub = async () => {
    const provider = new GithubAuthProvider();
    const cred = await signInWithPopup(auth, provider);
    if (cred.user) {
      await ensureUserProfile(cred.user.uid, { email: cred.user.email || "", displayName: cred.user.displayName || "" });
    }
  };

  const sendPasswordReset = async (email: string) => {
    await sendPasswordResetEmail(auth, email);
  };

  const signOut = async () => {
    await firebaseSignOut(auth);
  };

  return (
    <AuthContext.Provider value={{ user, idToken, loading, signIn, signUp, signInWithGoogle, signInWithGithub, sendPasswordReset, signOut }}>
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth() {
  return useContext(AuthContext);
}
