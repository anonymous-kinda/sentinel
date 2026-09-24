/**
 * Console logging with the repo's rule: the message is a stable,
 * low-cardinality key you can search for; values go in the fields and are
 * never interpolated into it. `log.error({ status }, "Pass unit save failed")`.
 */
type Fields = Record<string, unknown>;

export const log = {
  info: (fields: Fields, message: string) => console.info(message, fields),
  warn: (fields: Fields, message: string) => console.warn(message, fields),
  error: (fields: Fields, message: string) => console.error(message, fields),
};
