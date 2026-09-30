export interface Entity {
  table: string;
  label: string;
  title: string[];
  subtitle?: string[];
  search: string[];
  filters?: Record<string, string[]>;
  relations?: Record<string, string>;
  hidden?: string[];
  markdown?: string[];
  menu?: boolean;
  files?: string[];
  relationLabels?: Record<string, string>;
}
export const app: { name: string; authCollection: string; entities: Entity[] } =
  {
    name: "ChatContext",
    authCollection: "users",
    entities: [
      {
        table: "conversations",
        label: "Conversations",
        title: ["title"],
        search: ["id", "title", "kind"],
        subtitle: ["kind", "status"],
        filters: {
          kind: ["public_channel", "private_channel", "dm", "support"],
          status: ["open", "resolved"],
        },
        relations: {
          visitor: "user_directory",
          assignee: "user_directory",
        },
      },
      {
        table: "messages",
        label: "Messages",
        title: ["body"],
        search: ["id", "body"],
        subtitle: ["created"],
        markdown: ["body"],
        relations: {
          conversation: "conversations",
          parent: "messages",
          author: "user_directory",
        },
        hidden: ["mentions"],
      },
      {
        table: "attachments",
        label: "Attachments",
        title: ["original"],
        search: ["id", "original", "sha256"],
        relations: {
          message: "messages",
          author: "user_directory",
        },
        files: ["original"],
      },
      {
        table: "inbox",
        label: "Inbox",
        title: ["reason"],
        search: ["id", "reason"],
        relations: {
          message: "messages",
        },
        hidden: ["account"],
      },
      {
        table: "memberships",
        label: "Members",
        title: ["id"],
        search: ["id", "id"],
        relations: {
          conversation: "conversations",
          account: "user_directory",
        },
        menu: false,
      },
      {
        table: "reactions",
        label: "Reactions",
        title: ["emoji"],
        search: ["id", "emoji"],
        relations: {
          message: "messages",
          account: "user_directory",
        },
        menu: false,
      },
      {
        table: "read_receipts",
        label: "Read acknowledgements",
        title: ["created"],
        search: ["id", "created"],
        relations: {
          message: "messages",
          account: "user_directory",
        },
        menu: false,
      },
      {
        table: "user_directory",
        label: "People",
        title: ["name"],
        search: ["id", "name"],
        menu: false,
      },
    ],
  };
for (const e of app.entities)
  if (!["user_directory", "inbox"].includes(e.table))
    e.relations = {
      ...e.relations,
      created_by: "user_directory",
      updated_by: "user_directory",
    };
