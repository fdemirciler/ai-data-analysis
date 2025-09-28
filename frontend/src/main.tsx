
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./index.css";
import { AuthProvider } from "./context/AuthContext";
import { ChatProvider } from "./context/ChatContext";

createRoot(document.getElementById("root")!).render(
	<AuthProvider>
		<ChatProvider>
			<App />
		</ChatProvider>
	</AuthProvider>,
);
  