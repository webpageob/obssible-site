// Schema for the "post" content type — matches exactly what build.py's
// fetch_sanity_posts() expects. If a field name here changes, the GROQ
// query in build.py must change too, or the field silently comes back
// empty.
//
// Field-by-field mapping to the old posts/*.md frontmatter, so the two
// pipelines produce the same shape while both are live:
//   frontmatter "title:"  ->  title
//   frontmatter "slug:"   ->  slug.current
//   frontmatter "date:"   ->  date   (Sanity's date type, not datetime —
//                              matches build.py's YYYY-MM-DD validation)
//   markdown body          ->  body   (Portable Text: rich text + images)

import { defineField, defineType } from "sanity";

export const postType = defineType({
  name: "post",
  title: "Post",
  type: "document",
  fields: [
    defineField({
      name: "title",
      title: "Title",
      type: "string",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "slug",
      title: "Slug",
      type: "slug",
      description:
        "Becomes the web address: obssible.com/log/THIS-VALUE/. " +
        "Do not change this after publishing — it breaks shared links " +
        "and can cause the newsletter to resend the post.",
      options: { source: "title", maxLength: 96 },
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "date",
      title: "Date",
      type: "date",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "body",
      title: "Body",
      type: "array",
      of: [
        { type: "block" },
        {
          type: "image",
          fields: [
            defineField({
              name: "alt",
              title: "Alt text",
              type: "string",
              description: "Describe the image for screen readers and search engines.",
            }),
          ],
        },
      ],
    }),
  ],
  preview: {
    select: { title: "title", date: "date" },
    prepare({ title, date }) {
      return { title, subtitle: date };
    },
  },
});
