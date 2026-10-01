// Server-safe theme constants (the hook and the toggle live in ./theme).

export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "theme";
export const THEME_COLORS: Record<Theme, string> = { light: "#f4f5fa", dark: "#04050a" };

/**
 * Runs in <head> before first paint: restores a saved dark theme without a flash.
 * Light is the default, so nothing happens for first-time visitors.
 */
export const THEME_SCRIPT = `try{if(localStorage.getItem("${THEME_STORAGE_KEY}")==="dark"){document.documentElement.dataset.theme="dark";document.querySelector('meta[name="theme-color"]')?.setAttribute("content","${THEME_COLORS.dark}")}}catch(e){}`;
