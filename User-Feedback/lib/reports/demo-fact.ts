import type { FeedbackFactResponse, FeedbackFactRow, FilterOptions } from "./types";

function item(
    id: string,
    group: string,
    category: string,
    tag: string,
    extras: Partial<FeedbackFactRow> = {},
): FeedbackFactRow {
    const summary =
        extras.feedback_summary_ai ||
        `${tag} feedback captured for ${extras.product_name || group}.`;
    const excerpt =
        extras.feedback_excerpt ||
        `User mentioned ${tag.toLowerCase()} during the visit.`;
    const conversation =
        extras.full_conversation ||
        [
            "FME: Namaste, I am from Pidilite. How is the product working for you on site?",
            `User: ${excerpt}`,
            "FME: Can you walk me through the last job where you used it? Substrate, weather, pack size, anything that felt different from earlier lots.",
            "User: Last week we did a wardrobe in Marine ply. Humidity was high. Grab was good but open time felt short, so alignment of the laminate was rushed. Pack opening was also tight, glue came on the hands.",
            "FME: Did you compare with any other brand on that site?",
            "User: The contractor next door used a local adhesive. On wet plywood their grab slipped, ours held. Price they quoted was lower, that is why some dealers push it.",
            "FME: Any packaging or token issue we should take back to the team?",
            "User: Manufacturing date is hard to read. Token scan failed twice, then it worked. Please make the date and token clearer. Also share a short application video for monsoon sites.",
            "FME: Thank you. I will share this feedback with the product and loyalty teams. If stock is delayed, tell the dealer to raise it on the next visit.",
            "User: Okay. Please also tell them user meets should not have such long redemption queues. We wait more than the talk.",
            "FME: Noted. Anything else before I leave?",
            "User: That is all. Product is good, these small things if you fix, we will keep buying.",
        ].join("\n");
    return {
        feedback_id: id,
        job_id: `job-${id}`,
        feedback_group: group,
        feedback_category: category,
        feedback_tag: tag,
        data_source: "M-Power",
        division: "Fevicol",
        zone: "West",
        cluster: "Mumbai",
        state: "Maharashtra",
        feedback_summary_ai: summary,
        feedback_excerpt: excerpt,
        full_conversation: conversation,
        ...extras,
    };
}

function many(
    prefix: string,
    count: number,
    group: string,
    category: string,
    tag: string,
    extras: Partial<FeedbackFactRow> = {},
): FeedbackFactRow[] {
    return Array.from({ length: count }, (_, i) =>
        item(`${prefix}-${i + 1}`, group, category, tag, extras),
    );
}

export const DEMO_FACT_ROWS: FeedbackFactRow[] = [
    ...many("m-comp-q", 2, "PDT GROUP", "Competition", "Competition product - product quality", {
        product_name: "Marine",
        competitors_mentioned: "Fevicol Marine vs local brand",
        feedback_summary_ai:
            "Carpenter compared Marine grab with a local adhesive and said Pidilite holds better on wet plywood.",
        feedback_excerpt: "Marine ka grab local se better hai, plywood geela ho to bhi pakad rehta hai.",
    }),
    ...many("m-pack-q", 4, "PDT GROUP", "Product", "Product In Pack quality / packaging / application complaints", {
        product_name: "Marine",
        feedback_summary_ai: "Leakage and hard-to-open cap reported on Marine packs from last lot.",
        feedback_excerpt: "Last tin se glue nikal raha tha, cap tight hai kholna mushkil.",
    }),
    ...many("m-perf", 5, "PDT GROUP", "Product", "Existing Product - Performance improvements", {
        product_name: "Marine",
        feedback_summary_ai: "Users asked for faster grab and longer open time on Marine for monsoon sites.",
        feedback_excerpt: "Grab jaldi ho, lekin monsoon mein open time thoda zyada chahiye.",
    }),
    ...many("m-pkg", 3, "PDT GROUP", "Product", "Existing Product - Packaging improvements", {
        product_name: "Marine",
        feedback_summary_ai: "Request for clearer manufacturing date and easier token scan on Marine tins.",
        feedback_excerpt: "Date clearly dikhe aur token scan easily ho jaye.",
    }),
    ...many("fv-pack-q", 25, "PDT GROUP", "Product", "Product In Pack quality / packaging / application complaints", {
        product_name: "FV",
        feedback_summary_ai: "FV pack leakage and application bubbles reported across dealer counters.",
        feedback_excerpt: "FV ke pack se leak ho raha hai, lagate time bubble aa rahe hain.",
    }),
    ...many("fv-perf", 28, "PDT GROUP", "Product", "Existing Product - Performance improvements", {
        product_name: "FV",
        feedback_summary_ai: "Contractors want stronger bond and less smell on Fevicol SH / FV.",
        feedback_excerpt: "Bond strong chahiye, smell kam ho.",
    }),
    ...many("fv-pkg", 17, "PDT GROUP", "Product", "Existing Product - Packaging improvements", {
        product_name: "FV",
        feedback_summary_ai: "FV branding and token identification on pack needs to be easier to spot.",
        feedback_excerpt: "Pack par token pehchaan clear nahi hai.",
    }),
    ...many("u-fcc", 4, "USER GROUP", "Systems", "FCC App", {
        product_name: "FV",
        feedback_summary_ai: "Users reported login and point-sync delays on the FCC app.",
        feedback_excerpt: "App mein points late update hote hain.",
    }),
    ...many("u-site", 2, "USER GROUP", "User Engagement", "Site visits", {
        product_name: "Marine",
        feedback_summary_ai: "Positive response to site visits; asked for more technical demos.",
        feedback_excerpt: "Site visit se samajh aata hai, demo aur chahiye.",
    }),
    ...many("u-carn-food", 3, "USER GROUP", "User Meets", "Carnival", {
        product_name: "FV",
        feedback_sub_tag: "Bad Food",
        feedback_summary_ai: "Carnival food quality was poor and queues were long.",
        feedback_excerpt: "Carnival mein khana theek nahi tha, line bahut lambi thi.",
    }),
    ...many("u-carn-slow", 3, "USER GROUP", "User Meets", "Carnival", {
        product_name: "FV",
        feedback_sub_tag: "Slow redemption",
        feedback_summary_ai: "Gift redemption counter at Carnival was slow.",
        feedback_excerpt: "Redemption counter pe wait zyada ho raha tha.",
    }),
    ...many("u-carn-crowd", 2, "USER GROUP", "User Meets", "Carnival", {
        product_name: "Marine",
        feedback_sub_tag: "Too much crowd",
        feedback_summary_ai: "Carnival was overcrowded and difficult to hear the product talk.",
        feedback_excerpt: "Crowd zyada tha, baat sunai nahi di.",
    }),
    ...many("d-credit", 2, "DEALER GROUP", "Dealer-related", "Competition - Credit days", {
        product_name: "FV",
        feedback_summary_ai: "Dealer compared Pidilite 30-day credit with competition offering 90 days.",
        feedback_excerpt: "Competition 90 din credit de raha hai, company 30 din.",
    }),
    ...many("d-stock", 5, "DEALER GROUP", "Dealer-related", "Stock Issues", {
        product_name: "Marine",
        feedback_summary_ai: "Marine stock delay from distributor; dealer bought from wholesale.",
        feedback_excerpt: "Stock late aaya, wholesale se lena pada.",
    }),
    ...many("d-disg", 3, "DEALER GROUP", "Dealer-related", "Dealer Disgruntlement", {
        product_name: "FV",
        feedback_summary_ai: "Pending scheme settlement and fewer user meets for the dealer's key users.",
        feedback_excerpt: "Scheme pending hai, mere users ke liye meet nahi ho rahi.",
    }),
];

const DEMO_FILTERS: FilterOptions = {
    divisions: ["Fevicol"],
    zones: ["West"],
    clusters: ["Mumbai"],
    states: ["Maharashtra"],
    products: ["FV", "Marine"],
    data_sources: ["M-Power"],
    fme_codes: ["FME001"],
    user_types: ["Dealer", "Contractor"],
};

export function demoFeedbackFactResponse(): FeedbackFactResponse {
    return {
        success: true,
        message: "Showing sample feedback so you can preview the report locally.",
        data: {
            items: DEMO_FACT_ROWS,
            filter_options: DEMO_FILTERS,
            metadata: {
                total_items: DEMO_FACT_ROWS.length,
                returned_items: DEMO_FACT_ROWS.length,
                truncated: false,
                include_conversation: true,
            },
            source: "demo",
        },
    };
}
