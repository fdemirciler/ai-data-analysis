import { initializeApp, getApps } from "firebase/app";
import { getAuth } from "firebase/auth";
import { getFirestore } from "firebase/firestore";

// ✅ Static config from Firebase Console (Project Settings → General → SDK setup)
const firebaseConfig = {
  apiKey: "AIzaSyAm6Qmw7rXbNvYmkCgyLr25677Uy7NKlLU",
  authDomain: "ai-data-analyser.firebaseapp.com",
  projectId: "ai-data-analyser",
  storageBucket: "ai-data-analyser.appspot.com",
  messagingSenderId: "1012295827257",
  appId: "1:1012295827257:web:749760706a3d959f02f2e8",
  measurementId: "G-FH9B37VLFL",
};

// Prevent double initialization (important if this file is imported multiple times)
const app = !getApps().length ? initializeApp(firebaseConfig) : getApps()[0];

export const auth = getAuth(app);
export const db = getFirestore(app);
export default app;
