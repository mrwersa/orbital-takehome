import { motion } from "framer-motion";
import { Bot } from "lucide-react";
import { useState } from "react";
import { Streamdown } from "streamdown";
import "streamdown/styles.css";
import type { Citation, Message } from "../types";

// Above this, a quote is long enough to reliably wrap past two lines at the
// citation card's width and is worth clamping; below it, the clamp/toggle
// machinery would just be UI for text that already fits.
const QUOTE_CLAMP_THRESHOLD = 130;

// Stagger step between one citation card and the next, in seconds.
const CITATION_STAGGER_SECONDS = 0.04;

interface CitationCardProps {
	citation: Citation;
	onCitationClick?: (citation: Citation) => void;
	isActive: boolean;
	staggerIndex: number;
}

function CitationCard({
	citation,
	onCitationClick,
	isActive,
	staggerIndex,
}: CitationCardProps) {
	const [expanded, setExpanded] = useState(false);
	const isLong = citation.quote.length > QUOTE_CLAMP_THRESHOLD;

	return (
		<motion.div
			initial={{ opacity: 0, y: 4 }}
			animate={{ opacity: 1, y: 0 }}
			transition={{
				duration: 0.15,
				delay: staggerIndex * CITATION_STAGGER_SECONDS,
			}}
			className={`rounded-lg border text-xs transition-colors hover:bg-neutral-50 ${
				isActive
					? "border-neutral-900 bg-neutral-50"
					: "border-neutral-200 bg-white hover:border-neutral-300"
			}`}
		>
			<button
				type="button"
				onClick={() => onCitationClick?.(citation)}
				className="flex w-full items-start gap-2 px-2.5 py-1.5 text-left"
			>
				<span className="mt-0.5 flex-shrink-0 rounded-full bg-neutral-800 px-2 py-0.5 text-[10px] font-medium text-white">
					p.{citation.page}
				</span>
				<span
					className={`min-w-0 break-words text-neutral-600 ${isLong && !expanded ? "line-clamp-2" : ""}`}
				>
					"{citation.quote}"
				</span>
			</button>
			{isLong && (
				// Sibling to the button above, not nested inside it -- a button
				// inside a button is invalid HTML and breaks keyboard/screen
				// reader semantics. Toggling here never moves anything above
				// this card, only whatever comes after it in normal flow.
				<button
					type="button"
					onClick={() => setExpanded((value) => !value)}
					className="block w-full px-2.5 pb-1.5 text-left text-[10px] font-medium text-neutral-400 hover:text-neutral-600"
				>
					{expanded ? "Show less" : "Show more"}
				</button>
			)}
		</motion.div>
	);
}

interface MessageBubbleProps {
	message: Message;
	onCitationClick?: (citation: Citation) => void;
	currentPage: number;
	activeCitation: Citation | null;
}

export function MessageBubble({
	message,
	onCitationClick,
	currentPage,
	activeCitation,
}: MessageBubbleProps) {
	if (message.role === "system") {
		return (
			<motion.div
				initial={{ opacity: 0 }}
				animate={{ opacity: 1 }}
				transition={{ duration: 0.2 }}
				className="flex justify-center py-2"
			>
				<p className="text-xs text-neutral-400">{message.content}</p>
			</motion.div>
		);
	}

	if (message.role === "user") {
		return (
			<motion.div
				initial={{ opacity: 0, y: 8 }}
				animate={{ opacity: 1, y: 0 }}
				transition={{ duration: 0.2 }}
				className="flex justify-end py-1.5"
			>
				<div className="max-w-[75%] rounded-2xl rounded-br-md bg-neutral-100 px-4 py-2.5">
					<p className="whitespace-pre-wrap text-sm text-neutral-800">
						{message.content}
					</p>
				</div>
			</motion.div>
		);
	}

	// Assistant message
	return (
		<motion.div
			initial={{ opacity: 0, y: 8 }}
			animate={{ opacity: 1, y: 0 }}
			transition={{ duration: 0.2 }}
			className="flex gap-3 py-1.5"
		>
			<div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-neutral-900">
				<Bot className="h-4 w-4 text-white" />
			</div>
			<div className="min-w-0 max-w-[80%]">
				<div
					className={
						message.answer_supported === false
							? "prose rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2.5"
							: "prose"
					}
				>
					{message.answer_supported === false && (
						<p className="mb-1.5 text-xs font-medium text-neutral-500">
							The document does not confirm the following:
						</p>
					)}
					<Streamdown>{message.content}</Streamdown>
				</div>
				{message.citations && message.citations.length > 0 && (
					<div className="mt-1.5 flex flex-col gap-1.5">
						{message.citations.map((citation, index) => (
							<CitationCard
								key={`${citation.page}-${citation.quote}`}
								citation={citation}
								onCitationClick={onCitationClick}
								isActive={
									currentPage === citation.page &&
									activeCitation?.page === citation.page &&
									activeCitation?.quote === citation.quote
								}
								staggerIndex={index}
							/>
						))}
					</div>
				)}
			</div>
		</motion.div>
	);
}

interface StreamingBubbleProps {
	content: string;
	verifying?: boolean;
}

export function StreamingBubble({ content, verifying }: StreamingBubbleProps) {
	return (
		<div className="flex gap-3 py-1.5">
			<div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-neutral-900">
				<Bot className="h-4 w-4 text-white" />
			</div>
			<div className="min-w-0 max-w-[80%]">
				{content ? (
					<div className="prose">
						<Streamdown mode="streaming">{content}</Streamdown>
					</div>
				) : (
					<div className="flex items-center gap-1 py-2">
						<span className="h-1.5 w-1.5 animate-pulse rounded-full bg-neutral-400" />
						<span
							className="h-1.5 w-1.5 animate-pulse rounded-full bg-neutral-400"
							style={{ animationDelay: "0.15s" }}
						/>
						<span
							className="h-1.5 w-1.5 animate-pulse rounded-full bg-neutral-400"
							style={{ animationDelay: "0.3s" }}
						/>
					</div>
				)}
				{verifying ? (
					<p className="mt-1.5 text-xs text-neutral-400">
						Checking the quotes against the document…
					</p>
				) : (
					<span className="inline-block h-4 w-0.5 animate-pulse bg-neutral-400" />
				)}
			</div>
		</div>
	);
}
