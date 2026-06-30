# Task 2 — Judge-vs-Human Validation Sheet (stored-relation audit judge)

Judge = Qwen3-235B-A22B-Instruct (same as the 36.9% stored audit). For each item, read the EVIDENCE and the judge VERDICT, then write your label in `AUTHOR_LABEL:` (SUPPORTED / CO_MENTION / WRONG_DIRECTION / WRONG_PREDICATE / UNSUPPORTED) and `AGREE: y/n`.

Sample: 64 stored relations, <=2 per predicate. NOTE: this is a fresh stratified draw (the original 382 verdict file was not persisted), so it validates the SAME judge on the SAME population, not the identical 382 rows.

---

### 1. `acquired_by`  —  **Accenture plc** → **Alfahealth**
- Convention: subject = the ACQUIRED company; object = the ACQUIRER. Membership in an acquiring consortium counts (consortium incl. X acquiring Y => Y acquired_by X).
- Evidence:
  - Accenture Plc (ACN) on Wednesday announced an agreement to acquire Alfahealth, a subsidiary of Engineering Group, for undisclosed consideration.
  - Accenture (ACN) has agreed to acquire Alfahealth, a subsidiary of engineering Group, in a move aimed at strengthening its digital health capabilities and supporting the modernization of Italy's health system.
- JUDGE: **WRONG_DIRECTION** (Accenture is acquiring Alfahealth, so Alfahealth is acquired_by Accenture, not vice versa.)
- AUTHOR_LABEL: ____    AGREE: ____

### 2. `acquired_by`  —  **Astrobotic** → **Voyager Technologies, Inc.**
- Convention: subject = the ACQUIRED company; object = the ACQUIRER. Membership in an acquiring consortium counts (consortium incl. X acquiring Y => Y acquired_by X).
- Evidence:
  - buying space start-up Astrobotic for "up to $300 million"
- JUDGE: **UNSUPPORTED** (No mention of Voyager Technologies, Inc. in the evidence)
- AUTHOR_LABEL: ____    AGREE: ____

### 3. `analyst_rating`  —  **DA Davidson** → **Oracle Corporation**
- Convention: an analyst/firm issued a rating on a company. Convention: subject = the RATED COMPANY, object = the analyst/rating FIRM (e.g. Zacks). If no rating-firm is the object but a rating exists on the subject company, treat as SUPPORTED.
- Evidence:
  - On June 11, DA Davidson boosted its price objective on Oracle Corporation (NYSE:ORCL) from $200 to $225, while keeping a 'Buy' rating on the shares.
- JUDGE: **WRONG_DIRECTION** (DA Davidson issued the rating on Oracle, so Oracle is the subject per convention.)
- AUTHOR_LABEL: ____    AGREE: ____

### 4. `analyst_rating`  —  **RBC Capital** → **Banco Santander**
- Convention: an analyst/firm issued a rating on a company. Convention: subject = the RATED COMPANY, object = the analyst/rating FIRM (e.g. Zacks). If no rating-firm is the object but a rating exists on the subject company, treat as SUPPORTED.
- Evidence:
  - banks such as RBC Capital, Deutsche Bank, and Morgan Stanley have been active in adjusting price targets and ratings on Banco Santander.
- JUDGE: **WRONG_DIRECTION** (RBC Capital issued ratings on Banco Santander, so subject/object are reversed per convention.)
- AUTHOR_LABEL: ____    AGREE: ____

### 5. `appointed_as`  —  **Jake Conley** → **Yahoo TCW**
- Convention: subject = the COMPANY, object = the PERSON appointed to a formal role (new hire / appointment).
- Evidence:
  - Reporter Jake Conley joins Josh Lipton on Market Domination
- JUDGE: **WRONG_DIRECTION** (Snippet shows Jake Conley joined Yahoo TCW, not that Yahoo TCW was appointed to Jake Conley.)
- AUTHOR_LABEL: ____    AGREE: ____

### 6. `appointed_as`  —  **SpaceX** → **Roelof Botha**
- Convention: subject = the COMPANY, object = the PERSON appointed to a formal role (new hire / appointment).
- Evidence:
  - Space Exploration Technologies Corp. elected Roelof Botha to its board of directors on Monday, less than a week after the company went public in the largest IPO on record.
- JUDGE: **SUPPORTED** (SpaceX elected Roelof Botha to its board, which constitutes an appointment.)
- AUTHOR_LABEL: ____    AGREE: ____

### 7. `board_member_of`  —  **Dan Howley** → **Apple Inc.**
- Convention: subject = the PERSON, object = the COMPANY whose board they sit on.
- Evidence:
  - (no evidence)
- JUDGE: **NO_EVIDENCE** ()
- AUTHOR_LABEL: ____    AGREE: ____

### 8. `board_member_of`  —  **Robert Hammond** → **T1 Energy Inc.**
- Convention: subject = the PERSON, object = the COMPANY whose board they sit on.
- Evidence:
  - The nominees for T1's Board of Directors who were elected are ... Robert Hammond, ...
- JUDGE: **SUPPORTED** (Snippet states Robert Hammond is elected to T1's Board of Directors.)
- AUTHOR_LABEL: ____    AGREE: ____

### 9. `competes_with`  —  **Blackberry** → **NASDAQ**
- Convention: symmetric rivalry between two companies (direction is not meaningful; either order is fine).
- Evidence:
  - At the same time, the Dow lost 1.21%, and the tech-heavy Nasdaq lost 0.89%.
- JUDGE: **CO_MENTION** (Both mentioned in market context but no rivalry asserted)
- AUTHOR_LABEL: ____    AGREE: ____

### 10. `competes_with`  —  **Super Micro Computer Inc** → **NVIDIA Corporation**
- Convention: symmetric rivalry between two companies (direction is not meaningful; either order is fine).
- Evidence:
  - SMCI's liquid-cooled server racks became the dominant infrastructure for NVDA GPUs
- JUDGE: **UNSUPPORTED** (Mentions both companies but no rivalry or competition is asserted.)
- AUTHOR_LABEL: ____    AGREE: ____

### 11. `corporate_action`  —  **Fidelity Investments** → **shares of Carnival Corporation Ltd**
- Convention: subject = the COMPANY announcing a dividend / buyback / spin-off / split; object = the action or affected entity.
- Evidence:
  - Schwab, SoFi, Robinhood and Fidelity were listed in the IPO prospectus of Space Exploration Technologies Corp., SpaceX's formal name, as potentially offering shares to retail investors.
- JUDGE: **UNSUPPORTED** (No corporate action by Fidelity on Carnival shares mentioned.)
- AUTHOR_LABEL: ____    AGREE: ____

### 12. `corporate_action`  —  **GLOBE NEWSWIRE** → **PennyMac Financial Services**
- Convention: subject = the COMPANY announcing a dividend / buyback / spin-off / split; object = the action or affected entity.
- Evidence:
  - NEW YORK, June 17, 2026 (GLOBE NEWSWIRE) -- Leading securities law firm Bleichmar Fonti & Auld LLP announces an investigation into PennyMac Financial Services, Inc. (NYSE:PFSI) for potential violations of the federal securities laws.
- JUDGE: **UNSUPPORTED** (Globe Newswire is the news distributor, not the company announcing a corporate action.)
- AUTHOR_LABEL: ____    AGREE: ____

### 13. `credit_rating`  —  **Alexandria Real Estate Equities Inc** → **Zacks Investment Research**
- Convention: subject = the RATED COMPANY, object = the rating AGENCY issuing a credit rating.
- Evidence:
  - This real estate investment trust (REIT) carries a Zacks Rank #3 (Hold).
- JUDGE: **UNSUPPORTED** (Zacks is mentioned but not as issuing a credit rating for Alexandria.)
- AUTHOR_LABEL: ____    AGREE: ____

### 14. `credit_rating`  —  **Zacks Investment Research** → **Credo Technology Group**
- Convention: subject = the RATED COMPANY, object = the rating AGENCY issuing a credit rating.
- Evidence:
  - Credo Technology Group Holding Ltd. (CRDO) : Free Stock Analysis Report
- JUDGE: **WRONG_DIRECTION** (Convention has company as subject, agency as object; triple reverses roles)
- AUTHOR_LABEL: ____    AGREE: ____

### 15. `divested_from`  —  **PLATINUM EQUITY ADVISORS, LLC** → **Heat Controller**
- Convention: subject = the DIVESTING company; object = the DIVESTED entity (asset / unit / company sold).
- Evidence:
  - Platinum Equity today announced that it has signed a definitive agreement to sell Heat Controller, a leading HVAC equipment supplier, to Lennox (NYSE: LII).
- JUDGE: **SUPPORTED** (Platinum Equity agreed to sell Heat Controller, indicating divestiture.)
- AUTHOR_LABEL: ____    AGREE: ____

### 16. `divested_from`  —  **GE HealthCare Technologies Inc.** → **GE Aerospace**
- Convention: subject = the DIVESTING company; object = the DIVESTED entity (asset / unit / company sold).
- Evidence:
  - Spun off from industrial giant General Electric in 2023
- JUDGE: **WRONG_DIRECTION** (Snippet shows GE Aerospace spun off SUBJECT, not SUBJECT divesting OBJECT)
- AUTHOR_LABEL: ____    AGREE: ____

### 17. `downgraded_by`  —  **Leerink Partners** → **Johnson & Johnson**
- Convention: subject = the COMPANY downgraded; object = the analyst FIRM or rating AGENCY doing the downgrade.
- Evidence:
  - Leerink Partners discussed the firm on May 13th as it upgraded the shares to Outperform from Market Perform and raised the share price target to $265 from $252.
- JUDGE: **UNSUPPORTED** (Leerink Partners upgraded, not downgraded, Johnson & Johnson.)
- AUTHOR_LABEL: ____    AGREE: ____

### 18. `downgraded_by`  —  **Wall Street** → **Citi Trends Inc**
- Convention: subject = the COMPANY downgraded; object = the analyst FIRM or rating AGENCY doing the downgrade.
- Evidence:
  - Yet, Wall Street prices Oscar like a total dud. The stock trades at a pathetic 11.5x 2028 consensus EPS—scraping the absolute bottom of its peer group and sitting at roughly half the multiple of Alignment Healthcare (ALHC).
- JUDGE: **UNSUPPORTED** (Wall Street is used generically, not as a specific downgrading firm.)
- AUTHOR_LABEL: ____    AGREE: ____

### 19. `earnings_guidance`  —  **Wall Street** → **ESAB**
- Convention: subject = the COMPANY issuing forward earnings guidance; object = the guidance/metric.
- Evidence:
  - Forecasted revenues by Wall Street analysts signal a company's potential.
- JUDGE: **UNSUPPORTED** (Earnings guidance not issued by Wall Street; analysts forecast revenues.)
- AUTHOR_LABEL: ____    AGREE: ____

### 20. `earnings_guidance`  —  **Citi Trends Inc** → **ON Semiconductor Corporation**
- Convention: subject = the COMPANY issuing forward earnings guidance; object = the guidance/metric.
- Evidence:
  - The brokerage also lifted its earnings per share estimates for calendar years 2026, 2027 and 2028.
- JUDGE: **UNSUPPORTED** (No mention of Citi Trends or ON Semiconductor in snippet; no relation established.)
- AUTHOR_LABEL: ____    AGREE: ____

### 21. `earnings_released`  —  **SpaceX** → **Investors Title Co.**
- Convention: subject = the COMPANY reporting quarterly/annual earnings; object = the earnings/period.
- Evidence:
  - I see the same unbridled frenzy for SpaceX and, for that matter, Anthropic.
- JUDGE: **UNSUPPORTED** (No earnings or reporting entity mentioned; snippet only discusses investor interest.)
- AUTHOR_LABEL: ____    AGREE: ____

### 22. `earnings_released`  —  **Zacks Investment Research** → **Ford Motor Company**
- Convention: subject = the COMPANY reporting quarterly/annual earnings; object = the earnings/period.
- Evidence:
  - Ford crushed its earnings estimates by 230% in the last quarter, is aggressively building recurring revenue streams, and is finally seeing its biggest supply headwind lift with the restart of the Novelis facility.
- JUDGE: **WRONG_DIRECTION** (Ford is the company releasing earnings, not Zacks Investment Research.)
- AUTHOR_LABEL: ____    AGREE: ____

### 23. `employs`  —  **Pras Subramanian** → **Yahoo! Finance**
- Convention: subject = the COMPANY, object = the PERSON (ongoing employment). NEVER person as subject.
- Evidence:
  - Senior Autos Reporter Pras Subramanian joins Julie Hyman on Market Catalysts
  - Yahoo Finance Senior Reporter Pras Subramanian breaks down this unconventional public stock offering.
- JUDGE: **WRONG_DIRECTION** (Yahoo! Finance employs Pras Subramanian, not the reverse.)
- AUTHOR_LABEL: ____    AGREE: ____

### 24. `employs`  —  **Pattern Wealth** → **Dave Jackson**
- Convention: subject = the COMPANY, object = the PERSON (ongoing employment). NEVER person as subject.
- Evidence:
  - Based in Wayzata, the team is led by Jeremy Jackson and includes financial advisor Dave Jackson and client service associate Erika Holland.
- JUDGE: **CO_MENTION** (Dave Jackson is mentioned as part of Pattern Wealth's team but no explicit employment verb is used.)
- AUTHOR_LABEL: ____    AGREE: ____

### 25. `filed_lawsuit_against`  —  **Federal Trade Commission** → **Amazon**
- Convention: subject = the PLAINTIFF, object = the DEFENDANT.
- Evidence:
  - Amazon.com Inc (NASDAQ:AMZN) will potentially be hit with a lawsuit from the U.S. Federal Trade Commission with billions of dollars in penalty charges, Bloomberg reported Tuesday, citing people familiar with the matter.
- JUDGE: **SUPPORTED** (FTC is plaintiff planning lawsuit against Amazon as defendant.)
- AUTHOR_LABEL: ____    AGREE: ____

### 26. `filed_lawsuit_against`  —  **Bragar Eagel & Squire, P.C.** → **CVLT**
- Convention: subject = the PLAINTIFF, object = the DEFENDANT.
- Evidence:
  - announces that a class action lawsuit has been filed against Commvault Systems, Inc.
- JUDGE: **UNSUPPORTED** (No mention of Bragar Eagel filing lawsuit against CVLT)
- AUTHOR_LABEL: ____    AGREE: ____

### 27. `has_executive`  —  **Sportradar Group AG** → **Brandon Walker**
- Convention: subject = the COMPANY, object = the named EXECUTIVE PERSON (CEO/CFO/CTO/President/COO/MD/Chairman). The person is ALWAYS the object.
- Evidence:
  - following Brandon Walker, Esq. on LinkedIn
- JUDGE: **CO_MENTION** (Snippet mentions Brandon Walker but no executive role at Sportradar)
- AUTHOR_LABEL: ____    AGREE: ____

### 28. `has_executive`  —  **Klarna** → **Sebastian Siemiatkowski**
- Convention: subject = the COMPANY, object = the named EXECUTIVE PERSON (CEO/CFO/CTO/President/COO/MD/Chairman). The person is ALWAYS the object.
- Evidence:
  - Klarna’s co-founder and CEO, Sebastian Siemiatkowski
- JUDGE: **SUPPORTED** (Snippet identifies Sebastian Siemiatkowski as Klarna's CEO, fitting the convention.)
- AUTHOR_LABEL: ____    AGREE: ____

### 29. `headquartered_in`  —  **Lamb Weston Holdings Inc** → **San Diego**
- Convention: subject = the COMPANY, object = the PLACE (city or country) of its primary HQ.
- Evidence:
  - SAN DIEGO, May 29, 2026
- JUDGE: **CO_MENTION** (San Diego is mentioned but no explicit claim of headquarters location)
- AUTHOR_LABEL: ____    AGREE: ____

### 30. `headquartered_in`  —  **Gilead Sciences Inc** → **California**
- Convention: subject = the COMPANY, object = the PLACE (city or country) of its primary HQ.
- Evidence:
  - Founded in 1987 and headquartered in California, Gilead Sciences Inc. (NASDAQ:GILD) is a drug manufacturer
- JUDGE: **SUPPORTED** (Snippet states Gilead Sciences is headquartered in California.)
- AUTHOR_LABEL: ____    AGREE: ____

### 31. `investment_in`  —  **Vanda Research** → **NVIDIA Corporation**
- Convention: subject = the INVESTOR (fund/company), object = the INVESTEE.
- Evidence:
  - retail bought just $100mn of QQQ [Nasdaq ETF] and $88.2mn of NVDA over the same period.
- JUDGE: **UNSUPPORTED** (No mention of Vanda Research investing in NVIDIA.)
- AUTHOR_LABEL: ____    AGREE: ____

### 32. `investment_in`  —  **Berkshire Hathaway Inc** → **Delta Air Lines Inc**
- Convention: subject = the INVESTOR (fund/company), object = the INVESTEE.
- Evidence:
  - started a Delta Air Lines position
  - and started a Delta Air Lines position
- JUDGE: **CO_MENTION** (Snippets mention Delta Air Lines but not Berkshire Hathaway as investor)
- AUTHOR_LABEL: ____    AGREE: ____

### 33. `is_in_industry`  —  **ON Semiconductor Corporation** → **Energy Infrastructure Fund**
- Convention: subject = the COMPANY, object = the GICS INDUSTRY it belongs to.
- Evidence:
  - The GaNEXUS family targets AI data centers, industrial automation, and energy infrastructure
- JUDGE: **UNSUPPORTED** (No mention of Energy Infrastructure Fund as GICS industry for ON Semiconductor)
- AUTHOR_LABEL: ____    AGREE: ____

### 34. `is_in_industry`  —  **Landstar** → **Transportation**
- Convention: subject = the COMPANY, object = the GICS INDUSTRY it belongs to.
- Evidence:
  - Landstar (NASDAQ:LSTR) is a transportation company specializing in freight and last-mile delivery services.
- JUDGE: **SUPPORTED** (Snippet states Landstar is a transportation company, matching the convention.)
- AUTHOR_LABEL: ____    AGREE: ____

### 35. `is_in_sector`  —  **West Pharmaceutical Services Inc** → **Health Care**
- Convention: subject = the COMPANY, object = the broad GICS SECTOR it belongs to.
- Evidence:
  - EODHD fundamentals: Health Care sector classification.
  - EODHD fundamentals: Health Care sector classification.
  - EODHD fundamentals: Health Care sector classification.
- JUDGE: **SUPPORTED** (Multiple snippets confirm West Pharmaceutical Services Inc is classified in Health Care sector.)
- AUTHOR_LABEL: ____    AGREE: ____

### 36. `is_in_sector`  —  **Revvity Inc.** → **Health Care**
- Convention: subject = the COMPANY, object = the broad GICS SECTOR it belongs to.
- Evidence:
  - EODHD fundamentals: Health Care sector classification.
  - EODHD fundamentals: Health Care sector classification.
  - EODHD fundamentals: Health Care sector classification.
- JUDGE: **SUPPORTED** (Multiple snippets confirm Revvity Inc. is classified in the Health Care sector.)
- AUTHOR_LABEL: ____    AGREE: ____

### 37. `issues_debt`  —  **Arch Capital Group (U.S.) Inc.** → **2043 Notes**
- Convention: subject = the COMPANY issuing bonds / taking a loan; object = the debt instrument/lender.
- Evidence:
  - Arch Capital Group (U.S.) Inc. (the "2043 Notes Offeror") of its outstanding 5.144% Senior Notes due 2043 (the "2043 Notes")
- JUDGE: **SUPPORTED** (Arch Capital Group (U.S.) Inc. is identified as the '2043 Notes Offeror' for the 2043 Notes.)
- AUTHOR_LABEL: ____    AGREE: ____

### 38. `issues_debt`  —  **Robinhood Markets Inc** → **Convertible Senior Notes**
- Convention: subject = the COMPANY issuing bonds / taking a loan; object = the debt instrument/lender.
- Evidence:
  - Robinhood Markets (NASDAQ:HOOD) shares took a 4% hit on Monday following the fintech pioneer's announcement of a massive $2.0 billion private placement of convertible senior notes due in 2029.
- JUDGE: **SUPPORTED** (Robinhood's $2B private placement of convertible senior notes constitutes issuing debt.)
- AUTHOR_LABEL: ____    AGREE: ____

### 39. `listed_on`  —  **Paramount Global Class B** → **NYSE**
- Convention: subject = the COMPANY/security, object = the EXCHANGE its shares trade on.
- Evidence:
  - Innodata(NASDAQ:INOD) and PAR Technology(NYSE:PAR) ...
- JUDGE: **UNSUPPORTED** (No mention of Paramount Global Class B or its listing)
- AUTHOR_LABEL: ____    AGREE: ____

### 40. `listed_on`  —  **Lululemon Athletica Inc.** → **NASDAQ**
- Convention: subject = the COMPANY/security, object = the EXCHANGE its shares trade on.
- Evidence:
  - Lululemon Athletica(NASDAQ:LULU)
  - Lululemon (NASDAQ:LULU)
  - Lululemon Athletica's (NASDAQ: LULU)
- JUDGE: **SUPPORTED** (NASDAQ:LULU notation confirms Lululemon is listed on NASDAQ.)
- AUTHOR_LABEL: ____    AGREE: ____

### 41. `market_share_claim`  —  **Veralto Corporation** → **US Dollar**
- Convention: subject = the COMPANY, object = the market/segment in which a share % is claimed.
- Evidence:
  - recurring revenue streams (now 61% of total sales)
- JUDGE: **UNSUPPORTED** (No market share percentage claimed for Veralto in US Dollar market)
- AUTHOR_LABEL: ____    AGREE: ____

### 42. `market_share_claim`  —  **SpaceX** → **U.S.**
- Convention: subject = the COMPANY, object = the market/segment in which a share % is claimed.
- Evidence:
  - The comments add to a growing debate over whether investors are assigning too much value to SpaceX's businesses, which span launch services, satellite internet and social media, following one of the most closely watched public offerings in recent years.
  - SpaceX conducted over 80% of U.S. space launches last year
- JUDGE: **SUPPORTED** (Snippet 2 states SpaceX conducted over 80% of U.S. space launches, implying a market share claim in the U.S.)
- AUTHOR_LABEL: ____    AGREE: ____

### 43. `operates_in_country`  —  **KVH Industries** → **United States of America**
- Convention: subject = the COMPANY, object = the COUNTRY it has significant business in.
- Evidence:
  - Top 10 Growth Companies With High Insider Ownership In The United States
- JUDGE: **CO_MENTION** (Mentions KVH Industries and USA but no assertion of operations.)
- AUTHOR_LABEL: ____    AGREE: ____

### 44. `operates_in_country`  —  **BP PLC ADR** → **Azerbaijan**
- Convention: subject = the COMPANY, object = the COUNTRY it has significant business in.
- Evidence:
  - BP, the British oil and gas major, is slated to become the operator of the Babek gas field, a natural gas project offshore Azerbaijan
  - BP Plc.(NYSE:BP) has officially launched commercial production of natural gas from the deeper reservoirs of the Azeri-Chirag-Gunashli (ACG) block, Azerbaijan's largest oilfield.
- JUDGE: **SUPPORTED** (BP operates in Azerbaijan via gas projects like ACG and Babek.)
- AUTHOR_LABEL: ____    AGREE: ____

### 45. `owns_stake_in`  —  **Qatar Investment Authority** → **The AES Corporation**
- Convention: subject = the OWNER (company/person), object = the INVESTEE it owns equity in.
- Evidence:
  - The buying consortium also includes the California Public Employees' Retirement System and the Qatar Investment Authority.
- JUDGE: **CO_MENTION** (QIA mentioned in consortium but no link to AES ownership)
- AUTHOR_LABEL: ____    AGREE: ____

### 46. `owns_stake_in`  —  **Meta Platforms Inc.** → **Manus AI**
- Convention: subject = the OWNER (company/person), object = the INVESTEE it owns equity in.
- Evidence:
  - The move marks a significant step toward unwinding a $2 billion acquisition that Beijing has opposed.
- JUDGE: **UNSUPPORTED** (No mention of Meta Platforms or Manus AI in the snippet.)
- AUTHOR_LABEL: ____    AGREE: ____

### 47. `partner_of`  —  **Southwest Airlines Company** → **AWS**
- Convention: formal partnership / JV / alliance between two parties (direction not meaningful; either order is fine).
- Evidence:
  - Southwest Airlines ... is modernizing its technology architecture and moving away from a largely on-premises environment by partnering with Amazon Web Services (AWS) to become a fully cloud-based, AI-enabled airline by 2028.
- JUDGE: **SUPPORTED** (Snippet states Southwest is partnering with AWS, indicating a formal partnership.)
- AUTHOR_LABEL: ____    AGREE: ____

### 48. `partner_of`  —  **Atos Group** → **Crowdstrike Holdings Inc**
- Convention: formal partnership / JV / alliance between two parties (direction not meaningful; either order is fine).
- Evidence:
  - Atos, un leader mondial de la transformation digitale portée par la puissance de l’intelligence artificielle, annonce aujourd’hui rejoindre le projet QuiltWorks de CrowdStrike.
  - Atos, a global leader of AI-powered digital transformation, today announces that it has joined CrowdStrike’s Project QuiltWorks.
- JUDGE: **SUPPORTED** (Atos joining Project QuiltWorks indicates a formal alliance with CrowdStrike.)
- AUTHOR_LABEL: ____    AGREE: ____

### 49. `price_target`  —  **Susquehanna** → **Hewlett Packard Enterprise Co**
- Convention: subject = the COMPANY whose stock has a price target; object = the analyst/firm or the target.
- Evidence:
  - Bernstein and Susquehanna emphasize pricing power in servers.
- JUDGE: **UNSUPPORTED** (No price target mentioned for Hewlett Packard Enterprise Co by Susquehanna)
- AUTHOR_LABEL: ____    AGREE: ____

### 50. `price_target`  —  **Barclays** → **Centene Corp**
- Convention: subject = the COMPANY whose stock has a price target; object = the analyst/firm or the target.
- Evidence:
  - On May 26, Barclays increased its price target on Centene Corporation (NYSE:CNC) to $75 from $63
- JUDGE: **WRONG_DIRECTION** (Barclays set price target on Centene, so Centene is subject, not object per convention.)
- AUTHOR_LABEL: ____    AGREE: ____

### 51. `produces`  —  **$DOWI** → **Natural Gas**
- Convention: subject = the COMPANY, object = the PRODUCT or service it makes.
- Evidence:
  - FirstEnergy Corp. (FE), headquartered in Akron, Ohio, generates, transmits, and distributes electricity as well as explores, produces, and distributes natural gas.
- JUDGE: **UNSUPPORTED** (No mention of $DOWI producing natural gas in evidence)
- AUTHOR_LABEL: ____    AGREE: ____

### 52. `produces`  —  **Xfinity** → **America**
- Convention: subject = the COMPANY, object = the PRODUCT or service it makes.
- Evidence:
  - Xfinity brings Internet, mobile, entertainment, and smart home services into one simple, seamless solution – giving customers more speed, savings, and control over their connected lives.
- JUDGE: **UNSUPPORTED** (Xfinity produces services, not the country America)
- AUTHOR_LABEL: ____    AGREE: ____

### 53. `regulates`  —  **European Central Bank** → **UniCredit**
- Convention: subject = the REGULATOR (government body), object = the company/sector regulated.
- Evidence:
  - If the offer succeeds and is approved by the European Central Bank, it should mainly allow UniCredit to gradually increase its stake in Commerzbank and merge it with its German subsidiary HypoVereinsbank
- JUDGE: **SUPPORTED** (ECB approval required for UniCredit's actions, implying regulatory authority over UniCredit.)
- AUTHOR_LABEL: ____    AGREE: ____

### 54. `regulates`  —  **the Pentagon** → **China Telecom**
- Convention: subject = the REGULATOR (government body), object = the company/sector regulated.
- Evidence:
  - Other notable companies on the list are... China Telecom...
- JUDGE: **UNSUPPORTED** (Snippet lists China Telecom but does not state the Pentagon regulates it.)
- AUTHOR_LABEL: ____    AGREE: ____

### 55. `reported_revenue_of`  —  **Seagate Technology PLC** → **Ireland**
- Convention: subject = the COMPANY, object = the SEGMENT / GEOGRAPHY whose revenue was reported.
- Evidence:
  - (no evidence)
- JUDGE: **NO_EVIDENCE** ()
- AUTHOR_LABEL: ____    AGREE: ____

### 56. `reported_revenue_of`  —  **Bloomberg Intelligence** → **NVIDIA Corporation**
- Convention: subject = the COMPANY, object = the SEGMENT / GEOGRAPHY whose revenue was reported.
- Evidence:
  - Revenue in fiscal 2026 has since grown to $216 billion, according to CNBC.
- JUDGE: **UNSUPPORTED** (No mention of Bloomberg Intelligence reporting NVIDIA's revenue)
- AUTHOR_LABEL: ____    AGREE: ____

### 57. `revenue_from_country`  —  **Tesla Inc** → **Republic of Korea**
- Convention: subject = the COMPANY, object = the COUNTRY it derives material revenue from.
- Evidence:
  - The bank also highlighted favorable trends in other Asia-Pacific markets, including South Korea and Australia.
- JUDGE: **UNSUPPORTED** (Mentions South Korea but no revenue link to Tesla)
- AUTHOR_LABEL: ____    AGREE: ____

### 58. `revenue_from_country`  —  **OUTFRONT Media** → **U.S.**
- Convention: subject = the COMPANY, object = the COUNTRY it derives material revenue from.
- Evidence:
  - OUTFRONT is one of the largest U.S. out-of-home advertising operators, with billboard and transit displays in approximately 120 markets, including the 25 largest markets.
- JUDGE: **SUPPORTED** (OUTFRONT operates extensively in U.S. markets, implying material revenue from the country.)
- AUTHOR_LABEL: ____    AGREE: ____

### 59. `sentiment_signal`  —  **Wall Street** → **SpaceX**
- Convention: a general sentiment expression about the subject entity not captured by other predicates.
- Evidence:
  - Wall Street anticipates that Tesla and SpaceX will eventually merge
  - For much of the past month, Wall Street has been chanting the same three letters: SPCX, the Nasdaq ticker SpaceX intends to use when it begins trading on June 12, 2026.
- JUDGE: **SUPPORTED** (Wall Street's chanting of SPCX shows positive sentiment toward SpaceX)
- AUTHOR_LABEL: ____    AGREE: ____

### 60. `sentiment_signal`  —  **WTI** → **Trump**
- Convention: a general sentiment expression about the subject entity not captured by other predicates.
- Evidence:
  - Brent crude and WTI prices were gaining after President Donald Trump warned the U.S.-Iran peace deal is still subject to change.
- JUDGE: **UNSUPPORTED** (No sentiment about WTI directed toward Trump is expressed.)
- AUTHOR_LABEL: ____    AGREE: ____

### 61. `subsidiary_of`  —  **PGIM** → **Prudential Financial, Inc.**
- Convention: subject = the SUBSIDIARY, object = the PARENT company.
- Evidence:
  - PGIM,1 the $1.4 trillion global asset management business of Prudential Financial, Inc.
  - PGIM, the $1.4 trillion global asset management business of Prudential Financial, Inc.
- JUDGE: **SUPPORTED** (PGIM is described as the asset management business of Prudential, implying subsidiary relationship.)
- AUTHOR_LABEL: ____    AGREE: ____

### 62. `subsidiary_of`  —  **Arch Capital Group (U.S.) Inc.** → **Arch Capital Group Ltd.**
- Convention: subject = the SUBSIDIARY, object = the PARENT company.
- Evidence:
  - Arch Capital Group Ltd. ... provides insurance, reinsurance and mortgage insurance on a worldwide basis through its wholly owned subsidiaries.
- JUDGE: **SUPPORTED** (Arch Capital Group Ltd. owns subsidiaries, so its subsidiary is subsidiary_of it.)
- AUTHOR_LABEL: ____    AGREE: ____

### 63. `supplier_of`  —  **Schlumberger NV** → **BP PLC ADR**
- Convention: subject = the SUPPLIER, object = the BUYER it supplies goods/services to.
- Evidence:
  - SLB announced that its OneSubsea joint venture has been awarded a contract by BP p.l.c. BP to provide a subsea boosting system
- JUDGE: **SUPPORTED** (OneSubsea (SLB JV) contracted by BP, so Schlumberger supplies BP under convention.)
- AUTHOR_LABEL: ____    AGREE: ____

### 64. `supplier_of`  —  **Marvell Technology** → **Amazon**
- Convention: subject = the SUPPLIER, object = the BUYER it supplies goods/services to.
- Evidence:
  - While Marvell has more than 20 custom chip customers, its biggest customer is Amazon, which uses some of Marvell's IP for its Trainium chip.
  - It came from a report about what Amazon (NASDAQ: AMZN) might do with a line of chips that Marvell helps design.
  - Marvell's custom chip customers, such as Amazon
- JUDGE: **SUPPORTED** (Snippet 1 states Amazon is Marvell's biggest customer, implying Marvell supplies it.)
- AUTHOR_LABEL: ____    AGREE: ____
