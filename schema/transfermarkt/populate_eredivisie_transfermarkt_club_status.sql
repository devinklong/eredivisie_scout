-- Active: 1785293463866@@127.0.0.1@5432@postgres
-- populate_eredivisie_club_status.sql
-- INSERT statements for eredivisie_club_status, built from the manual
-- Wikipedia season-by-season compilation (2026-08-29). Covers 2010-11
-- through 2025-26 (season_id 2010-2025). Club IDs match the Transfermarkt
-- IDs used in pipelines/transfermarkt/scrape_all_eredivisie_clubs.py.
-- Every row here is was_eredivisie = TRUE, since only seasons where a
-- club was actually confirmed in the top flight were compiled -- there
-- are no FALSE rows to insert; a club/season pair simply absent from
-- this table means "not confirmed Eredivisie," which downstream queries
-- should treat as effectively FALSE (a LEFT JOIN + IS NULL check, not a
-- literal FALSE row lookup).

INSERT INTO eredivisie_club_status (club_id, club_name, season_id, was_eredivisie) VALUES
-- 2010-11
(1268, 'ADO Den Haag', 2010, TRUE), (610, 'Ajax', 2010, TRUE), (1090, 'AZ', 2010, TRUE),
(798, 'Excelsior', 2010, TRUE), (234, 'Feyenoord', 2010, TRUE), (642, 'De Graafschap', 2010, TRUE),
(202, 'Groningen', 2010, TRUE), (306, 'Heerenveen', 2010, TRUE), (1304, 'Heracles Almelo', 2010, TRUE),
(132, 'NAC Breda', 2010, TRUE), (467, 'NEC Nijmegen', 2010, TRUE), (383, 'PSV', 2010, TRUE),
(192, 'Roda JC', 2010, TRUE), (317, 'Twente', 2010, TRUE), (200, 'Utrecht', 2010, TRUE),
(499, 'Vitesse', 2010, TRUE), (1426, 'VVV Venlo', 2010, TRUE), (403, 'Willem II', 2010, TRUE),
-- 2011-12
(1268, 'ADO Den Haag', 2011, TRUE), (610, 'Ajax', 2011, TRUE), (1090, 'AZ', 2011, TRUE),
(798, 'Excelsior', 2011, TRUE), (234, 'Feyenoord', 2011, TRUE), (642, 'De Graafschap', 2011, TRUE),
(202, 'Groningen', 2011, TRUE), (306, 'Heerenveen', 2011, TRUE), (1304, 'Heracles Almelo', 2011, TRUE),
(132, 'NAC Breda', 2011, TRUE), (467, 'NEC Nijmegen', 2011, TRUE), (383, 'PSV', 2011, TRUE),
(235, 'RKC Waalwijk', 2011, TRUE), (192, 'Roda JC', 2011, TRUE), (317, 'Twente', 2011, TRUE),
(200, 'Utrecht', 2011, TRUE), (499, 'Vitesse', 2011, TRUE), (1426, 'VVV Venlo', 2011, TRUE),
-- 2012-13
(1268, 'ADO Den Haag', 2012, TRUE), (610, 'Ajax', 2012, TRUE), (1090, 'AZ', 2012, TRUE),
(234, 'Feyenoord', 2012, TRUE), (202, 'Groningen', 2012, TRUE), (306, 'Heerenveen', 2012, TRUE),
(1304, 'Heracles Almelo', 2012, TRUE), (132, 'NAC Breda', 2012, TRUE), (467, 'NEC Nijmegen', 2012, TRUE),
(383, 'PSV', 2012, TRUE), (235, 'RKC Waalwijk', 2012, TRUE), (192, 'Roda JC', 2012, TRUE),
(317, 'Twente', 2012, TRUE), (200, 'Utrecht', 2012, TRUE), (499, 'Vitesse', 2012, TRUE),
(1426, 'VVV Venlo', 2012, TRUE), (403, 'Willem II', 2012, TRUE),
-- 2013-14
(1268, 'ADO Den Haag', 2013, TRUE), (610, 'Ajax', 2013, TRUE), (1090, 'AZ', 2013, TRUE),
(133, 'Cambuur', 2013, TRUE), (234, 'Feyenoord', 2013, TRUE), (1435, 'Go Ahead Eagles', 2013, TRUE),
(202, 'Groningen', 2013, TRUE), (306, 'Heerenveen', 2013, TRUE), (1304, 'Heracles Almelo', 2013, TRUE),
(132, 'NAC Breda', 2013, TRUE), (467, 'NEC Nijmegen', 2013, TRUE), (1269, 'PEC Zwolle', 2013, TRUE),
(383, 'PSV', 2013, TRUE), (235, 'RKC Waalwijk', 2013, TRUE), (192, 'Roda JC', 2013, TRUE),
(317, 'Twente', 2013, TRUE), (200, 'Utrecht', 2013, TRUE), (499, 'Vitesse', 2013, TRUE),
-- 2014-15
(1268, 'ADO Den Haag', 2014, TRUE), (610, 'Ajax', 2014, TRUE), (1090, 'AZ', 2014, TRUE),
(133, 'Cambuur', 2014, TRUE), (1455, 'Dordrecht', 2014, TRUE), (798, 'Excelsior', 2014, TRUE),
(234, 'Feyenoord', 2014, TRUE), (1435, 'Go Ahead Eagles', 2014, TRUE), (202, 'Groningen', 2014, TRUE),
(306, 'Heerenveen', 2014, TRUE), (1304, 'Heracles Almelo', 2014, TRUE), (132, 'NAC Breda', 2014, TRUE),
(1269, 'PEC Zwolle', 2014, TRUE), (383, 'PSV', 2014, TRUE), (317, 'Twente', 2014, TRUE),
(200, 'Utrecht', 2014, TRUE), (499, 'Vitesse', 2014, TRUE), (403, 'Willem II', 2014, TRUE),
-- 2015-16
(1268, 'ADO Den Haag', 2015, TRUE), (610, 'Ajax', 2015, TRUE), (1090, 'AZ', 2015, TRUE),
(133, 'Cambuur', 2015, TRUE), (642, 'De Graafschap', 2015, TRUE), (798, 'Excelsior', 2015, TRUE),
(234, 'Feyenoord', 2015, TRUE), (202, 'Groningen', 2015, TRUE), (306, 'Heerenveen', 2015, TRUE),
(1304, 'Heracles Almelo', 2015, TRUE), (467, 'NEC Nijmegen', 2015, TRUE), (1269, 'PEC Zwolle', 2015, TRUE),
(383, 'PSV', 2015, TRUE), (192, 'Roda JC', 2015, TRUE), (317, 'Twente', 2015, TRUE),
(200, 'Utrecht', 2015, TRUE), (499, 'Vitesse', 2015, TRUE), (403, 'Willem II', 2015, TRUE),
-- 2016-17
(1268, 'ADO Den Haag', 2016, TRUE), (610, 'Ajax', 2016, TRUE), (1090, 'AZ', 2016, TRUE),
(798, 'Excelsior', 2016, TRUE), (234, 'Feyenoord', 2016, TRUE), (1435, 'Go Ahead Eagles', 2016, TRUE),
(202, 'Groningen', 2016, TRUE), (306, 'Heerenveen', 2016, TRUE), (1304, 'Heracles Almelo', 2016, TRUE),
(467, 'NEC Nijmegen', 2016, TRUE), (1269, 'PEC Zwolle', 2016, TRUE), (383, 'PSV', 2016, TRUE),
(192, 'Roda JC', 2016, TRUE), (468, 'Sparta', 2016, TRUE), (317, 'Twente', 2016, TRUE),
(200, 'Utrecht', 2016, TRUE), (499, 'Vitesse', 2016, TRUE), (403, 'Willem II', 2016, TRUE),
-- 2017-18
(1268, 'ADO Den Haag', 2017, TRUE), (610, 'Ajax', 2017, TRUE), (1090, 'AZ', 2017, TRUE),
(798, 'Excelsior', 2017, TRUE), (234, 'Feyenoord', 2017, TRUE), (202, 'Groningen', 2017, TRUE),
(306, 'Heerenveen', 2017, TRUE), (1304, 'Heracles Almelo', 2017, TRUE), (132, 'NAC Breda', 2017, TRUE),
(1269, 'PEC Zwolle', 2017, TRUE), (383, 'PSV', 2017, TRUE), (192, 'Roda JC', 2017, TRUE),
(468, 'Sparta', 2017, TRUE), (317, 'Twente', 2017, TRUE), (200, 'Utrecht', 2017, TRUE),
(499, 'Vitesse', 2017, TRUE), (1426, 'VVV Venlo', 2017, TRUE), (403, 'Willem II', 2017, TRUE),
-- 2018-19
(1268, 'ADO Den Haag', 2018, TRUE), (610, 'Ajax', 2018, TRUE), (1090, 'AZ', 2018, TRUE),
(642, 'De Graafschap', 2018, TRUE), (1283, 'Emmen', 2018, TRUE), (798, 'Excelsior', 2018, TRUE),
(234, 'Feyenoord', 2018, TRUE), (385, 'Fortuna Sittard', 2018, TRUE), (202, 'Groningen', 2018, TRUE),
(306, 'Heerenveen', 2018, TRUE), (1304, 'Heracles Almelo', 2018, TRUE), (132, 'NAC Breda', 2018, TRUE),
(1269, 'PEC Zwolle', 2018, TRUE), (383, 'PSV', 2018, TRUE), (200, 'Utrecht', 2018, TRUE),
(499, 'Vitesse', 2018, TRUE), (1426, 'VVV Venlo', 2018, TRUE), (403, 'Willem II', 2018, TRUE),
-- 2019-20
(1268, 'ADO Den Haag', 2019, TRUE), (610, 'Ajax', 2019, TRUE), (1090, 'AZ', 2019, TRUE),
(1283, 'Emmen', 2019, TRUE), (234, 'Feyenoord', 2019, TRUE), (385, 'Fortuna Sittard', 2019, TRUE),
(202, 'Groningen', 2019, TRUE), (306, 'Heerenveen', 2019, TRUE), (1304, 'Heracles Almelo', 2019, TRUE),
(1269, 'PEC Zwolle', 2019, TRUE), (383, 'PSV', 2019, TRUE), (235, 'RKC Waalwijk', 2019, TRUE),
(468, 'Sparta', 2019, TRUE), (317, 'Twente', 2019, TRUE), (200, 'Utrecht', 2019, TRUE),
(499, 'Vitesse', 2019, TRUE), (1426, 'VVV Venlo', 2019, TRUE), (403, 'Willem II', 2019, TRUE),
-- 2020-21
(1268, 'ADO Den Haag', 2020, TRUE), (610, 'Ajax', 2020, TRUE), (1090, 'AZ', 2020, TRUE),
(1283, 'Emmen', 2020, TRUE), (234, 'Feyenoord', 2020, TRUE), (385, 'Fortuna Sittard', 2020, TRUE),
(202, 'Groningen', 2020, TRUE), (306, 'Heerenveen', 2020, TRUE), (1304, 'Heracles Almelo', 2020, TRUE),
(1269, 'PEC Zwolle', 2020, TRUE), (383, 'PSV', 2020, TRUE), (235, 'RKC Waalwijk', 2020, TRUE),
(468, 'Sparta', 2020, TRUE), (317, 'Twente', 2020, TRUE), (200, 'Utrecht', 2020, TRUE),
(499, 'Vitesse', 2020, TRUE), (1426, 'VVV Venlo', 2020, TRUE), (403, 'Willem II', 2020, TRUE),
-- 2021-22
(610, 'Ajax', 2021, TRUE), (1090, 'AZ', 2021, TRUE), (133, 'Cambuur', 2021, TRUE),
(234, 'Feyenoord', 2021, TRUE), (385, 'Fortuna Sittard', 2021, TRUE), (1435, 'Go Ahead Eagles', 2021, TRUE),
(202, 'Groningen', 2021, TRUE), (306, 'Heerenveen', 2021, TRUE), (1304, 'Heracles Almelo', 2021, TRUE),
(467, 'NEC Nijmegen', 2021, TRUE), (1269, 'PEC Zwolle', 2021, TRUE), (383, 'PSV', 2021, TRUE),
(235, 'RKC Waalwijk', 2021, TRUE), (468, 'Sparta', 2021, TRUE), (317, 'Twente', 2021, TRUE),
(200, 'Utrecht', 2021, TRUE), (499, 'Vitesse', 2021, TRUE), (403, 'Willem II', 2021, TRUE),
-- 2022-23
(610, 'Ajax', 2022, TRUE), (1090, 'AZ', 2022, TRUE), (133, 'Cambuur', 2022, TRUE),
(1283, 'Emmen', 2022, TRUE), (798, 'Excelsior', 2022, TRUE), (234, 'Feyenoord', 2022, TRUE),
(385, 'Fortuna Sittard', 2022, TRUE), (1435, 'Go Ahead Eagles', 2022, TRUE), (202, 'Groningen', 2022, TRUE),
(306, 'Heerenveen', 2022, TRUE), (467, 'NEC Nijmegen', 2022, TRUE), (383, 'PSV', 2022, TRUE),
(235, 'RKC Waalwijk', 2022, TRUE), (468, 'Sparta', 2022, TRUE), (317, 'Twente', 2022, TRUE),
(200, 'Utrecht', 2022, TRUE), (499, 'Vitesse', 2022, TRUE), (724, 'Volendam', 2022, TRUE),
-- 2023-24
(610, 'Ajax', 2023, TRUE), (723, 'Almere City', 2023, TRUE), (1090, 'AZ', 2023, TRUE),
(798, 'Excelsior', 2023, TRUE), (234, 'Feyenoord', 2023, TRUE), (385, 'Fortuna Sittard', 2023, TRUE),
(1435, 'Go Ahead Eagles', 2023, TRUE), (306, 'Heerenveen', 2023, TRUE), (1304, 'Heracles Almelo', 2023, TRUE),
(467, 'NEC Nijmegen', 2023, TRUE), (1269, 'PEC Zwolle', 2023, TRUE), (383, 'PSV', 2023, TRUE),
(235, 'RKC Waalwijk', 2023, TRUE), (468, 'Sparta', 2023, TRUE), (317, 'Twente', 2023, TRUE),
(200, 'Utrecht', 2023, TRUE), (499, 'Vitesse', 2023, TRUE), (724, 'Volendam', 2023, TRUE),
-- 2024-25
(610, 'Ajax', 2024, TRUE), (723, 'Almere City', 2024, TRUE), (1090, 'AZ', 2024, TRUE),
(234, 'Feyenoord', 2024, TRUE), (385, 'Fortuna Sittard', 2024, TRUE), (1435, 'Go Ahead Eagles', 2024, TRUE),
(202, 'Groningen', 2024, TRUE), (306, 'Heerenveen', 2024, TRUE), (1304, 'Heracles Almelo', 2024, TRUE),
(132, 'NAC Breda', 2024, TRUE), (467, 'NEC Nijmegen', 2024, TRUE), (1269, 'PEC Zwolle', 2024, TRUE),
(383, 'PSV', 2024, TRUE), (235, 'RKC Waalwijk', 2024, TRUE), (468, 'Sparta', 2024, TRUE),
(317, 'Twente', 2024, TRUE), (200, 'Utrecht', 2024, TRUE), (403, 'Willem II', 2024, TRUE),
-- 2025-26
(610, 'Ajax', 2025, TRUE), (1090, 'AZ', 2025, TRUE), (798, 'Excelsior', 2025, TRUE),
(234, 'Feyenoord', 2025, TRUE), (385, 'Fortuna Sittard', 2025, TRUE), (1435, 'Go Ahead Eagles', 2025, TRUE),
(202, 'Groningen', 2025, TRUE), (306, 'Heerenveen', 2025, TRUE), (1304, 'Heracles Almelo', 2025, TRUE),
(132, 'NAC Breda', 2025, TRUE), (467, 'NEC Nijmegen', 2025, TRUE), (1269, 'PEC Zwolle', 2025, TRUE),
(383, 'PSV', 2025, TRUE), (468, 'Sparta', 2025, TRUE), (1434, 'Telstar', 2025, TRUE),
(317, 'Twente', 2025, TRUE), (200, 'Utrecht', 2025, TRUE), (724, 'Volendam', 2025, TRUE);

SELECT * FROM eredivisie_club_status ORDER BY season_id, club_id;
SELECT COUNT(*) FROM eredivisie_club_status;  
INSERT INTO eredivisie_club_status (club_id, club_name, season_id, was_eredivisie) -- missed this one, caught after count was 287 not 288
VALUES (1269, 'PEC Zwolle', 2012, TRUE);