CREATE TABLE Company
(
    CompanyId             bigint NOT NULL,
    isLocatedIn_CountryId bigint NOT NULL
);
CREATE TABLE University
(
    UniversityId       bigint NOT NULL,
    isLocatedIn_CityId bigint NOT NULL
);
CREATE TABLE Continent
(
    ContinentId bigint NOT NULL
);
CREATE TABLE Country
(
    CountryId            bigint NOT NULL,
    isPartOf_ContinentId bigint NOT NULL
);
CREATE TABLE City
(
    CityId             bigint NOT NULL,
    isPartOf_CountryId bigint NOT NULL
);
CREATE TABLE Tag
(
    TagId              bigint NOT NULL,
    hasType_TagClassId bigint NOT NULL
);
CREATE TABLE TagClass
(
    TagClassId              bigint NOT NULL,
    isSubclassOf_TagClassId bigint -- null for the root TagClass
);
CREATE TABLE Forum
(
    ForumId               bigint NOT NULL,
    hasModerator_PersonId bigint NOT NULL
);
CREATE TABLE Comment
(
    CommentId             bigint NOT NULL,
    hasCreator_PersonId   bigint NOT NULL,
    isLocatedIn_CountryId bigint NOT NULL,
    replyOf_PostId        bigint,
    replyOf_CommentId     bigint -- either replyOf_PostId or replyOf_CommentId is NULL
);
CREATE TABLE Post
(
    PostId                bigint NOT NULL,
    hasCreator_PersonId   bigint NOT NULL,
    Forum_containerOfId   bigint NOT NULL,
    isLocatedIn_CountryId bigint NOT NULL
);
CREATE TABLE Person
(
    PersonId           bigint NOT NULL,
    isLocatedIn_CityId bigint NOT NULL
);

CREATE TABLE Comment_hasTag_Tag
(
    CommentId bigint NOT NULL,
    TagId     bigint NOT NULL
);
CREATE TABLE Post_hasTag_Tag
(
    PostId bigint NOT NULL,
    TagId  bigint NOT NULL
);
CREATE TABLE Forum_hasMember_Person
(
    ForumId  bigint NOT NULL,
    PersonId bigint NOT NULL
);
CREATE TABLE Forum_hasTag_Tag
(
    ForumId bigint NOT NULL,
    TagId   bigint NOT NULL
);
CREATE TABLE Person_hasInterest_Tag
(
    PersonId bigint NOT NULL,
    TagId    bigint NOT NULL
);
CREATE TABLE Person_likes_Comment
(
    PersonId  bigint NOT NULL,
    CommentId bigint NOT NULL
);
CREATE TABLE Person_likes_Post
(
    PersonId bigint NOT NULL,
    PostId   bigint NOT NULL
);
CREATE TABLE Person_studyAt_University
(
    PersonId     bigint NOT NULL,
    UniversityId bigint NOT NULL
);
CREATE TABLE Person_workAt_Company
(
    PersonId  bigint NOT NULL,
    CompanyId bigint NOT NULL
);
CREATE TABLE Person_knows_Person
(
    Person1Id bigint NOT NULL,
    Person2Id bigint NOT NULL
);

\copy Company FROM 'PATHVAR/Company.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy University FROM 'PATHVAR/University.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Continent FROM 'PATHVAR/Continent.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Country FROM 'PATHVAR/Country.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy City FROM 'PATHVAR/City.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Forum FROM 'PATHVAR/Forum.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Comment FROM 'PATHVAR/Comment.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Post FROM 'PATHVAR/Post.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Person FROM 'PATHVAR/Person.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Tag FROM 'PATHVAR/Tag.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy TagClass FROM 'PATHVAR/TagClass.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Comment_hasTag_Tag FROM 'PATHVAR/Comment_hasTag_Tag.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Post_hasTag_Tag FROM 'PATHVAR/Post_hasTag_Tag.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Forum_hasMember_Person FROM 'PATHVAR/Forum_hasMember_Person.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Forum_hasTag_Tag FROM 'PATHVAR/Forum_hasTag_Tag.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Person_hasInterest_Tag FROM 'PATHVAR/Person_hasInterest_Tag.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Person_likes_Comment FROM 'PATHVAR/Person_likes_Comment.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Person_likes_Post FROM 'PATHVAR/Person_likes_Post.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Person_studyAt_University FROM 'PATHVAR/Person_studyAt_University.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Person_workAt_Company FROM 'PATHVAR/Person_workAt_Company.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Person_knows_Person (Person1id, Person2id) FROM 'PATHVAR/Person_knows_Person.csv' (DELIMITER '|', HEADER, FORMAT csv);
\copy Person_knows_Person (Person2id, Person1id) FROM 'PATHVAR/Person_knows_Person.csv' (DELIMITER '|', HEADER, FORMAT csv);

CREATE VIEW Comment_replyOf_Message AS
SELECT CommentId, replyOf_PostId AS ParentMessageId
FROM Comment
WHERE replyOf_PostId IS NOT NULL
UNION ALL
SELECT CommentId, replyOf_CommentId AS ParentMessageId
FROM Comment
WHERE replyOf_CommentId IS NOT NULL;

CREATE VIEW Message_hasCreator_Person AS
SELECT CommentId AS MessageId, hasCreator_PersonId
FROM Comment
UNION ALL
SELECT PostId AS MessageId, hasCreator_PersonId
FROM Post;

CREATE VIEW Message_hasTag_Tag AS
SELECT CommentId AS MessageId, TagId
FROM Comment_hasTag_Tag
UNION ALL
SELECT PostId AS MessageId, TagId
FROM Post_hasTag_Tag;

CREATE VIEW Message_isLocatedIn_Country AS
SELECT CommentId AS MessageId, isLocatedIn_CountryId
FROM Comment
UNION ALL
SELECT PostId AS MessageId, isLocatedIn_CountryId
FROM Post;

CREATE VIEW Person_likes_Message AS
SELECT PersonId, CommentId AS MessageId
FROM Person_likes_Comment
UNION ALL
SELECT PersonId, PostId AS MessageId
FROM Person_likes_Post;
