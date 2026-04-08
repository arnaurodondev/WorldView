import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { gateway } from "../lib/gateway-client";
import { OHLCVChart } from "../components/OHLCVChart";
import { NewsList } from "../components/NewsList";
import { SimilarCompaniesPanel } from "../components/SimilarCompaniesPanel";

export function CompanyDetailPage() {
  const { id } = useParams<{ id: string }>();

  const { data, isLoading, error } = useQuery({
    queryKey: ["company", id],
    queryFn: () => gateway.getCompanyOverview(id!),
    enabled: !!id,
  });

  if (isLoading) return <p>Loading...</p>;
  if (error) return <p>Error loading company data.</p>;
  if (!data) return null;

  return (
    <div>
      <h2>{data.company_id}</h2>
      <section style={{ marginBottom: "2rem" }}>
        <h3>Price Chart</h3>
        <OHLCVChart data={data.ohlcv.bars ?? []} />
      </section>
      <section style={{ marginBottom: "2rem" }}>
        <h3>Latest News</h3>
        <NewsList articles={data.latest_news.articles ?? []} />
      </section>
      <SimilarCompaniesPanel entityId={id!} />
    </div>
  );
}
