from jobspy import scrape_jobs

jobs = scrape_jobs(
    site_name=["indeed", "linkedin", "hellowork"],
    search_term="développeur",
    location="Nantes",
    results_wanted=100,
    hours_old=72,
    country_indeed="france",
)
print(f"Trouvé {len(jobs)} offres")
jobs.to_csv("jobs.csv", index=False)
