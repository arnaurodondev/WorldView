import { useQuery } from "@tanstack/react-query";
import { gateway } from "../lib/gateway-client";
import { NewsList } from "../components/NewsList";
import { PredictionMarketsPanel } from "../components/PredictionMarketsPanel";

export function NewsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["news", "relevant"],
    queryFn: () => gateway.getRelevantNews(30),
  });

  return (
    <div>
      <h2>News</h2>
      {isLoading ? (
        <p>Loading...</p>
      ) : (
        <NewsList articles={data?.articles ?? []} />
      )}
      <PredictionMarketsPanel />
    </div>
  );
}
