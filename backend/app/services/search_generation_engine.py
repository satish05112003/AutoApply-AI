import logging
from typing import List, Dict, Any, Optional
from app.models.profile import Preferences

logger = logging.getLogger("autoapply_ai.services.search_generation")

class SearchGenerationEngine:
    @staticmethod
    def generate_search_configs(prefs: Preferences) -> List[Dict[str, Any]]:
        """
        Dynamically generate a list of search queries and configurations
        based on the user's detailed Preferences model.
        """
        configs = []
        if not prefs:
            return configs

        # Extract roles, locations, sources from preferences
        roles = prefs.preferred_roles or ["Software Engineer"]
        locations = prefs.preferred_locations or ["Remote"]
        
        # Sources to crawl, default to a robust list if empty
        sources = prefs.preferred_sources or ["linkedin", "indeed", "naukri", "unstop", "wellfound"]
        sources = [s.lower().strip() for s in sources if s]
        if not sources:
            sources = ["linkedin", "indeed", "naukri", "unstop", "wellfound", "ashby", "greenhouse", "lever"]

        for source in sources:
            for role in roles:
                for loc in locations:
                    config = {
                        "source": source,
                        "query": role,
                        "location": loc,
                        "params": {}
                    }
                    
                    # 1. Platform-specific query configurations
                    if source == "linkedin":
                        # Mapping remote preferences to LinkedIn f_WT parameters:
                        # 1 = On-site, 2 = Remote, 3 = Hybrid
                        remote_pref = (prefs.remote_preference or "REMOTE").upper()
                        if remote_pref == "REMOTE":
                            config["params"]["f_WT"] = "2"
                            # If remote, location should usually be United States/India or similar country level
                            if loc.lower() == "remote":
                                config["location"] = "United States"
                        elif remote_pref == "HYBRID":
                            config["params"]["f_WT"] = "3"
                        elif remote_pref == "ONSITE":
                            config["params"]["f_WT"] = "1"

                        # Mapping experience level to LinkedIn f_E parameters:
                        # 1 = Internship, 2 = Entry level, 3 = Associate, 4 = Mid-Senior, 5 = Director, 6 = Executive
                        exp_level = (prefs.experience_level or "FRESHER").upper()
                        if exp_level == "FRESHER" or exp_level == "INTERN":
                            config["params"]["f_E"] = "1,2"
                        elif exp_level == "JUNIOR":
                            config["params"]["f_E"] = "2,3"
                        elif exp_level == "MID":
                            config["params"]["f_E"] = "3,4"
                        elif exp_level == "SENIOR":
                            config["params"]["f_E"] = "4,5"

                    elif source == "naukri":
                        # Naukri experience query param in years
                        exp_level = (prefs.experience_level or "FRESHER").upper()
                        if exp_level == "FRESHER":
                            config["params"]["experience"] = 0
                        elif exp_level == "JUNIOR":
                            config["params"]["experience"] = 2
                        elif exp_level == "MID":
                            config["params"]["experience"] = 5
                        elif exp_level == "SENIOR":
                            config["params"]["experience"] = 9
                        
                        # Exclude remote if location is remote or remote preference is active
                        remote_pref = (prefs.remote_preference or "REMOTE").upper()
                        if remote_pref == "REMOTE" or loc.lower() == "remote":
                            config["params"]["is_remote"] = True

                    elif source == "indeed":
                        # Indeed remote attribute: DSQP0
                        remote_pref = (prefs.remote_preference or "REMOTE").upper()
                        if remote_pref == "REMOTE" or loc.lower() == "remote":
                            config["params"]["sc"] = "0kf:attr(DSQP0);"
                        
                        # Experience limits
                        exp_level = (prefs.experience_level or "FRESHER").upper()
                        if exp_level == "FRESHER":
                            config["params"]["explvl"] = "entry_level"
                        elif exp_level == "SENIOR":
                            config["params"]["explvl"] = "senior_level"

                    # 2. Blacklisted keywords / companies metadata
                    config["blacklisted_companies"] = prefs.blacklisted_companies or []
                    config["blacklisted_keywords"] = prefs.blacklisted_keywords or []
                    config["min_salary_inr"] = prefs.min_salary_inr
                    config["max_salary_inr"] = prefs.max_salary_inr
                    config["work_authorization"] = prefs.work_authorization
                    
                    configs.append(config)

        logger.info(f"SearchGenerationEngine: Generated {len(configs)} search configurations for preferences user_id={prefs.user_id}")
        return configs
