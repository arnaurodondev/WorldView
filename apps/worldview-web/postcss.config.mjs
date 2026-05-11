/**
 * postcss.config.mjs — PostCSS configuration for Tailwind CSS v3
 *
 * WHY THIS EXISTS: Tailwind CSS v3 is a PostCSS plugin. This config tells
 * PostCSS to process CSS with Tailwind and autoprefixer.
 * autoprefixer adds vendor prefixes for browser compatibility (Chrome 120+,
 * Firefox 120+, Safari 17+ per NFR).
 */
const config = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};

export default config;
