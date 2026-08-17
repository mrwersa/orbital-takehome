import { useCallback, useEffect, useState } from "react";
import { ChatSidebar } from "./components/ChatSidebar";
import { ChatWindow } from "./components/ChatWindow";
import { DocumentViewer } from "./components/DocumentViewer";
import { TooltipProvider } from "./components/ui/tooltip";
import { useConversations } from "./hooks/use-conversations";
import { useDocument } from "./hooks/use-document";
import { useMessages } from "./hooks/use-messages";
import type { Citation } from "./types";

export default function App() {
	const {
		conversations,
		selectedId,
		loading: conversationsLoading,
		create,
		select,
		remove,
		refresh: refreshConversations,
	} = useConversations();

	const {
		messages,
		loading: messagesLoading,
		error: messagesError,
		streaming,
		streamingContent,
		verifying,
		send,
	} = useMessages(selectedId);

	const {
		document,
		upload,
		refresh: refreshDocument,
	} = useDocument(selectedId);

	// Owned here so a citation chip (inside ChatWindow) can move the viewer
	// to that citation's page. Reset on conversation change so switching
	// conversations doesn't leave the viewer on a stale page.
	const [currentPage, setCurrentPage] = useState(1);
	// Which specific citation was last clicked, so a click on one citation
	// doesn't also mark every other citation elsewhere in the conversation
	// that happens to cite the same page -- currentPage alone can't tell
	// those apart, since it's just a number. Reset alongside currentPage.
	const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
	// biome-ignore lint/correctness/useExhaustiveDependencies: selectedId is an intentional trigger to reset the page on conversation change
	useEffect(() => {
		setCurrentPage(1);
		setActiveCitation(null);
	}, [selectedId]);

	const handleCitationClick = useCallback((citation: Citation) => {
		setCurrentPage(citation.page);
		setActiveCitation(citation);
	}, []);

	// Any page change that didn't come from clicking a citation -- the
	// viewer's own Prev/Next controls -- clears the marked citation rather
	// than leaving it to silently reappear if the user pages back to that
	// same number later. "Keep it marked while the viewer is on that page"
	// means for as long as that click is still why the page is showing,
	// not "resurrect it whenever navigation happens to land there again."
	const handlePageChange = useCallback((page: number) => {
		setCurrentPage(page);
		setActiveCitation(null);
	}, []);

	const handleSend = useCallback(
		async (content: string) => {
			await send(content);
			refreshConversations();
		},
		[send, refreshConversations],
	);

	const handleUpload = useCallback(
		async (file: File) => {
			const doc = await upload(file);
			if (doc) {
				refreshDocument();
				refreshConversations();
			}
		},
		[upload, refreshDocument, refreshConversations],
	);

	const handleCreate = useCallback(async () => {
		await create();
	}, [create]);

	return (
		<TooltipProvider delayDuration={200}>
			<div className="flex h-screen bg-neutral-50">
				<ChatSidebar
					conversations={conversations}
					selectedId={selectedId}
					loading={conversationsLoading}
					onSelect={select}
					onCreate={handleCreate}
					onDelete={remove}
				/>

				<ChatWindow
					messages={messages}
					loading={messagesLoading}
					error={messagesError}
					streaming={streaming}
					streamingContent={streamingContent}
					verifying={verifying}
					hasDocument={!!document}
					conversationId={selectedId}
					onSend={handleSend}
					onUpload={handleUpload}
					onCitationClick={handleCitationClick}
					currentPage={currentPage}
					activeCitation={activeCitation}
				/>

				<DocumentViewer
					document={document}
					currentPage={currentPage}
					onPageChange={handlePageChange}
				/>
			</div>
		</TooltipProvider>
	);
}
