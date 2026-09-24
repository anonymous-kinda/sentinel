/** What a panel shows before its data arrives: that it is loading, or,
 *  when the request failed, what is unavailable and the server's reason. */
export function Pending({ what, error, loading = "Loading…" }: { what: string; error: string | null; loading?: string }) {
  if (error) {
    return (
      <div className="empty" role="alert">
        {what} unavailable: {error}
      </div>
    );
  }
  return <div className="empty">{loading}</div>;
}
