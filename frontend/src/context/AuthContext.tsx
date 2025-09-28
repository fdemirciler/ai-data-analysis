import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { UserIdentity } from "../types/chat";

interface AuthContextValue {
	user: UserIdentity | null;
	isAuthenticated: boolean;
	login: (payload: { name: string; email: string }) => void;
	logout: () => void;
}

const STORAGE_KEY = "ada-auth";

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function deriveUid(email: string) {
	const existing = localStorage.getItem(`${STORAGE_KEY}::uid::${email}`);
	if (existing) return existing;
	const uid = crypto.randomUUID();
	localStorage.setItem(`${STORAGE_KEY}::uid::${email}`, uid);
	return uid;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
	const [user, setUser] = useState<UserIdentity | null>(null);

	useEffect(() => {
		try {
			const raw = localStorage.getItem(STORAGE_KEY);
			if (!raw) return;
			const parsed = JSON.parse(raw) as UserIdentity;
			setUser(parsed);
		} catch (error) {
			console.warn("Failed to restore auth state", error);
		}
	}, []);

	const login = useCallback((payload: { name: string; email: string }) => {
		const identity: UserIdentity = {
			uid: deriveUid(payload.email.toLowerCase()),
			name: payload.name,
			email: payload.email.toLowerCase(),
		};
		setUser(identity);
		localStorage.setItem(STORAGE_KEY, JSON.stringify(identity));
	}, []);

	const logout = useCallback(() => {
		setUser(null);
		localStorage.removeItem(STORAGE_KEY);
	}, []);

	const value = useMemo<AuthContextValue>(
		() => ({
			user,
			isAuthenticated: Boolean(user),
			login,
			logout,
		}),
		[user, login, logout],
	);

	return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
	const ctx = useContext(AuthContext);
	if (!ctx) {
		throw new Error("useAuth must be used within AuthProvider");
	}
	return ctx;
}
