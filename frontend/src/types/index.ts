export interface Property {
  id: number;
  title: string;
  location: string;
  neighbourhood: string;
  county: string;
  property_type: string;
  bedrooms: number;
  bathrooms: number;
  price_kes: number;
  furnished: boolean;
  description: string;
}

export interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
}

export interface ChatResponse {
  conversation_id: string;
  reply: string;
  properties: Property[];
  tool_calls: ToolCall[];
  history_reset: boolean;
}

export type ChatMessage =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; text: string; properties: Property[]; toolCalls: ToolCall[]; historyReset: boolean }
  | { id: string; role: "error"; text: string; retryText: string };
