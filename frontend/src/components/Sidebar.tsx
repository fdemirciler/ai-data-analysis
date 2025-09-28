import { useState } from "react";
import { MessageCircle, Trash2, User, LogOut, Plus, X } from "lucide-react";
import { Button } from "./ui/button";
import { Separator } from "./ui/separator";
import { ScrollArea } from "./ui/scroll-area";

interface ChatSession {
  id: string;
  title: string;
  lastActivity: string;
  isActive?: boolean;
}

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  onNewChat: () => void;
  onSelectChat: (chatId: string) => void;
  onDeleteChat: (chatId: string) => void;
  onDeleteAllData: () => void;
  onLogout: () => void;
  sessions: { id: string; title: string; lastActivityAt: string; updatedAt: string; activeDatasetIds: string[] }[];
  activeSessionId: string | null;
  upload: { status: "idle" | "uploading" | "uploaded" | "error"; progress?: number; message?: string };
}

export function Sidebar({ 
  isOpen, 
  onClose, 
  onNewChat, 
  onSelectChat, 
  onDeleteChat, 
  onDeleteAllData, 
  onLogout,
  sessions,
  activeSessionId,
  upload,
}: SidebarProps) {
  const [chatSessions] = useState<ChatSession[]>([
    { id: "1", title: "Sales Data Analysis", lastActivity: "2h ago", isActive: true },
    { id: "2", title: "Customer Insights", lastActivity: "1d ago" },
    { id: "3", title: "Revenue Trends", lastActivity: "3d ago" },
  ]);

  const uploadLabel = (() => {
    switch (upload.status) {
      case "uploading":
        return `Uploading ${(upload.progress ?? 0) * 100 | 0}%`;
      case "uploaded":
        return "Upload complete";
      case "error":
        return upload.message ?? "Upload failed";
      default:
        return null;
    }
  })();

  return (
    <>
      {isOpen && (
        <div 
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={onClose}
        />
      )}
      
      <aside className={`
        fixed left-0 top-0 h-full w-80 bg-sidebar border-r border-sidebar-border z-50
        transform transition-transform duration-200 ease-in-out
        ${isOpen ? 'translate-x-0' : '-translate-x-full'}
        md:relative md:z-auto
      `}>
        <div className="flex flex-col h-full">
          <div className="flex items-center justify-between p-4 border-b border-sidebar-border">
            <h2 className="font-medium text-sidebar-foreground">Chat History</h2>
            <Button
              variant="ghost"
              size="sm"
              onClick={onClose}
              className="md:hidden"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>

          <div className="p-4">
            <Button 
              onClick={onNewChat}
              className="w-full justify-start gap-2"
              variant="outline"
            >
              <Plus className="h-4 w-4" />
              New Chat
            </Button>
          </div>

          <ScrollArea className="flex-1 px-4">
            <div className="space-y-2">
              {chatSessions.map((chat) => (
                <div
                  key={chat.id}
                  className={`
                    group flex items-center gap-3 p-3 rounded-lg cursor-pointer
                    hover:bg-sidebar-accent transition-colors
                    ${chat.id === activeSessionId ? 'bg-sidebar-accent' : ''}
                  `}
                  onClick={() => onSelectChat(chat.id)}
                >
                  <MessageCircle className="h-4 w-4 text-sidebar-foreground/60" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-sidebar-foreground truncate">
                      {chat.title}
                    </p>
                    <p className="text-xs text-sidebar-foreground/60">
                      {chat.lastActivity}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteChat(chat.id);
                    }}
                    className="opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              ))}
            </div>
          </ScrollArea>

          <div className="p-4 border-t border-sidebar-border space-y-4">
            {uploadLabel && (
              <div className="flex items-center gap-2 text-xs text-sidebar-foreground/70 bg-sidebar-accent rounded-md px-3 py-2">
                <span>{uploadLabel}</span>
              </div>
            )}

            <div className="text-xs text-sidebar-foreground/60 flex items-center gap-2">
              <span>Connection:</span>
              <span className="font-medium text-sidebar-foreground">{upload.status}</span>
            </div>

            <Separator />

            <div className="flex items-center gap-3">
              <div className="w-8 h-8 bg-sidebar-primary rounded-full flex items-center justify-center">
                <User className="h-4 w-4 text-sidebar-primary-foreground" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-sidebar-foreground truncate">
                  Demo User
                </p>
                <p className="text-xs text-sidebar-foreground/60 truncate">
                  demo@example.com
                </p>
              </div>
            </div>

            <div className="space-y-2">
              <Button
                variant="destructive"
                size="sm"
                onClick={onDeleteAllData}
                className="w-full justify-start gap-2"
              >
                <Trash2 className="h-4 w-4" />
                Delete All Data
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={onLogout}
                className="w-full justify-start gap-2"
              >
                <LogOut className="h-4 w-4" />
                Logout
              </Button>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}

interface PanelProps {
	sessions: ChatSession[];
	activeSessionId: string | null;
	onSelectChat: (id: string) => void;
	onNewChat: () => void;
	onDeleteChat: (id: string) => void;
	uploadLabel: string | null;
	connection: ConnectionState;
	usage: UsageState;
	quotaPercent: number;
	onDeleteAllData: () => void;
	onLogout: () => void;
	onClose?: () => void;
	user: UserIdentity;
}

function MobilePanel({
	onClose,
	sessions,
	activeSessionId,
	onSelectChat,
	onNewChat,
	onDeleteChat,
	uploadLabel,
	connection,
	usage,
	quotaPercent,
	onDeleteAllData,
	onLogout,
	user,
}: PanelProps & { onClose?: () => void }) {
	return (
		<div className="flex h-full flex-col">
			<div className="flex items-center justify-between border-b border-white/20 px-5 py-4">
				<h2 className="text-sm font-medium text-foreground/80">Chat History</h2>
				<Button variant="ghost" size="icon" className="rounded-full" onClick={onClose}>
					<X className="h-4 w-4" />
				</Button>
			</div>
			<div className="px-5 py-4">
				<Button onClick={onNewChat} className="w-full rounded-full bg-primary text-primary-foreground hover:bg-primary/90">
					<Plus className="mr-2 h-4 w-4" /> New Chat
				</Button>
			</div>
			<ScrollArea className="flex-1 px-5">
				<div className="space-y-3 pb-6">
					{sessions.map((chat) => (
						<div
							key={chat.id}
							onClick={() => {
								onSelectChat(chat.id);
								onClose?.();
							}}
							className={`rounded-2xl border border-white/10 px-4 py-3 shadow-sm transition-all ${
								chat.id === activeSessionId ? "bg-white/20" : "bg-white/10"
							}`}
						>
							<div className="flex items-start justify-between">
								<div>
									<p className="text-sm font-medium text-foreground/90">{chat.title}</p>
									<p className="text-xs text-foreground/60">
										{new Date(chat.lastActivityAt ?? chat.updatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
									</p>
								</div>
								<Button
									variant="ghost"
									size="icon"
									className="rounded-full bg-white/10"
									onClick={(event) => {
										event.stopPropagation();
										onDeleteChat(chat.id);
									}}
								>
									<Trash2 className="h-3.5 w-3.5" />
								</Button>
							</div>
							{chat.activeDatasetIds.length > 0 && (
								<p className="mt-2 text-[11px] text-foreground/50">
									{chat.activeDatasetIds.length} dataset{chat.activeDatasetIds.length > 1 ? "s" : ""}
								</p>
							)}
						</div>
					))}
				</div>
			</ScrollArea>
			<div className="space-y-4 border-t border-white/15 px-5 py-4 text-sm text-foreground/70">
				{uploadLabel && (
					<div className="rounded-2xl bg-white/15 px-4 py-3 text-xs">
						{uploadLabel}
					</div>
				)}
				<div>
					<div className="flex justify-between text-[11px] uppercase tracking-wider text-foreground/50">
						<span>Connection</span>
						<span className="text-foreground/80">{connection}</span>
					</div>
					<div className="mt-2 h-2 w-full rounded-full bg-white/15">
						<div
							className="h-2 rounded-full bg-primary/70"
							style={{ width: `${quotaPercent}%` }}
						/>
					</div>
					<div className="mt-1 text-[11px] text-foreground/50">{usage.count} / {usage.limit} daily runs</div>
				</div>
				<div className="flex items-center gap-3 rounded-2xl bg-white/10 px-4 py-3">
					<div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/15 text-primary">
						<User className="h-4 w-4" />
					</div>
					<div className="min-w-0">
						<p className="truncate text-sm font-medium text-foreground/90">{user.name}</p>
						<p className="truncate text-xs text-foreground/60">{user.email}</p>
					</div>
				</div>
				<div className="flex flex-col gap-2">
					<Button
						variant="ghost"
						className="rounded-full bg-red-500/15 text-red-500"
						onClick={onDeleteAllData}
					>
						<Trash2 className="mr-2 h-4 w-4" /> Delete All Data
					</Button>
					<Button
						variant="ghost"
						className="rounded-full bg-white/10 text-foreground/80"
						onClick={onLogout}
					>
						<LogOut className="mr-2 h-4 w-4" /> Logout
					</Button>
				</div>
			</div>
		</div>
	);
}