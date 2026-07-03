/// <reference types="vite/client" />

// Fontsource packages ship CSS only (no type declarations). These are
// side-effect imports for their font CSS — declare them as bare modules so the
// editor's TS server stops flagging "cannot find module" (the CLI build already
// resolves them via each package's ``exports`` map → its ``index.css``).
declare module "@fontsource-variable/*";
declare module "@fontsource/*";
