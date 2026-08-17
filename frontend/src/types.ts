export interface Conversation {
	id: string;
	title: string;
	created_at: string;
	updated_at: string;
	has_document: boolean;
}

export interface Citation {
	quote: string;
	page: number;
	clause?: string | null;
}

// A citation identified by which message it belongs to and its position
// within that message's citation list, not just its page and quote --
// two different messages can genuinely cite the identical text on the
// identical page, and the backend doesn't dedupe a message's own proposed
// quotes, so even one message can contain the same page+quote pair twice.
// Neither case is distinguishable by content alone.
export interface ActiveCitation extends Citation {
	messageId: string;
	index: number;
}

export interface Message {
	id: string;
	conversation_id: string;
	role: "user" | "assistant" | "system";
	content: string;
	sources_cited: number;
	citations?: Citation[];
	answer_supported?: boolean | null;
	created_at: string;
}

export interface Document {
	id: string;
	conversation_id: string;
	filename: string;
	page_count: number;
	uploaded_at: string;
}

export interface ConversationDetail extends Conversation {
	document?: Document;
}
