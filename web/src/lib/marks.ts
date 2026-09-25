/** An SVG path for a diamond of half-width `r` centred on (x, y): the mark
 *  that sets a point apart from the plot's circles by shape, not colour. */
export function diamond(x: number, y: number, r: number): string {
  return `M${x},${y - r}L${x + r},${y}L${x},${y + r}L${x - r},${y}Z`;
}
